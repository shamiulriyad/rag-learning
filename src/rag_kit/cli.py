"""Command-line interface for the RAG toolkit (`rag-kit`, or `python -m rag_kit`).

    rag-kit check [--deep] [--llm]      validate config, dependencies, store
    rag-kit ingest FILE [FILE ...]      steps 1-6 (re-ingesting replaces)
    rag-kit ask "question"              steps 7-11 (no question = interactive)
    rag-kit search "question"           retrieval only, no LLM call
    rag-kit documents [--json]          files in the collection + chunk counts
    rag-kit delete FILE_NAME            remove one document's chunks
    rag-kit serve                       FastAPI service (needs rag-kit[api])
    rag-kit ui                          Streamlit test UI (needs rag-kit[ui])

The project (its .env, documents and Qdrant data) is --project DIR if given,
else RAG_PROJECT_DIR, else the nearest folder at or above the current
directory that contains rag-kit.toml. Every command takes --project and
--collection (to work on something other than COLLECTION_NAME).
"""

import argparse
import contextlib
import importlib.metadata
import importlib.resources
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from rag_kit.env import export_env_file
from rag_kit.errors import RagError
from rag_kit.log import show_progress
from rag_kit.settings import Settings, set_default_settings

DISTRIBUTION = "rag-kit"


def _pipeline(args):
    from rag_kit.pipeline import Pipeline
    return Pipeline(collection=args.collection, settings=args.settings)


def _quiet(args):
    """With --json, step progress goes to stderr so stdout is only the JSON."""
    if getattr(args, "json", False):
        return contextlib.redirect_stdout(sys.stderr)
    return contextlib.nullcontext()


# --- check -------------------------------------------------------------------
# The package metadata (pyproject.toml) is the single source of truth for
# dependencies; each optional group is an extra.
EXTRA_PURPOSE = {
    "local": "local embeddings",
    "gemini": "Gemini",
    "api": "serve",
    "ui": "ui",
    "dev": "tests",
}


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_groups(requirements) -> list:
    """(distribution name, extra or None for core) for each Requires-Dist line
    that applies here, in order. References to rag-kit itself are skipped."""
    from packaging.requirements import Requirement

    groups = []
    for line in requirements:
        requirement = Requirement(line)
        if _canonical(requirement.name) == DISTRIBUTION:
            continue
        # Core first: a marker without `extra` (e.g. python_version) is true for
        # every extra too, so it must not be filed under the first one.
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            groups.append((requirement.name, None))
            continue
        extras = [extra for extra in EXTRA_PURPOSE
                  if requirement.marker.evaluate({"extra": extra})]
        if extras:
            groups.append((requirement.name, extras[0]))
    return groups


def dependency_report(requirements=None):
    """(all required installed?, [(status, name, detail), ...])."""
    if requirements is None:
        try:
            requirements = importlib.metadata.requires(DISTRIBUTION) or []
        except importlib.metadata.PackageNotFoundError:
            return False, [("FAIL", DISTRIBUTION, "is not installed as a package: "
                                                  "pip install rag-kit (or pip install -e .)")]
    ok, rows, seen = True, [], set()
    for name, extra in requirement_groups(requirements):
        if _canonical(name) in seen:
            continue
        seen.add(_canonical(name))
        required = extra is None
        purpose = "core" if required else f"optional: {EXTRA_PURPOSE[extra]}"
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            ok = ok and not required
            hint = "pip install rag-kit" if required else f'pip install "rag-kit[{extra}]"'
            rows.append(("FAIL" if required else "--", name, f"not installed ({purpose}): {hint}"))
        else:
            rows.append(("ok", name, f"{version} ({purpose})"))
    return ok, rows


def _missing_env_hint(settings) -> str:
    """How to create the missing settings file. Without it QDRANT_PATH is unset,
    so rag-kit would look for a Qdrant server instead of a local store."""
    defaults = f"until then defaults apply (Qdrant server at {settings.qdrant_url}, no API key)"
    if settings.env_file != settings.project_dir / ".env":
        return f"RAG_ENV_FILE points to a missing file; {defaults}"
    if (settings.project_dir / ".env.example").exists():
        return ("not created yet. In the project folder run `cp .env.example .env` "
                "(PowerShell: `Copy-Item .env.example .env`), then set GOOGLE_API_KEY; "
                f"{defaults}")
    return (f"not created yet. Create .env in {settings.project_dir} (variables are listed "
            f"in the rag-kit README); {defaults}")


def cmd_check(args) -> int:
    ok = True

    def line(status: str, label: str, detail: str = "") -> None:
        print(f"  [{status:^4}] {label:<22} {detail}")

    settings = args.settings
    if settings is None:
        ok = False
        print("Project     : not found")
        line("FAIL", "project", str(args.settings_error))
    else:
        env_file = settings.env_file
        print(f"Project     : {settings.project_dir}")
        print(f"Config file : {env_file} ({'found' if env_file.exists() else 'MISSING'})")
    print(f"Python      : {sys.version.split()[0]}")
    if settings is not None and not settings.env_file.exists():
        line("warn", ".env", _missing_env_hint(settings))

    if settings is not None:
        try:
            settings.validate()
            line("ok", "settings", f"chunk {settings.chunk_size}/{settings.chunk_overlap}, "
                                   f"top_k {settings.top_k}")
        except RagError as exc:
            ok = False
            line("FAIL", "settings", str(exc))

        line("ok" if settings.google_api_key else "warn", "GOOGLE_API_KEY",
             "set" if settings.google_api_key else "missing - `ask` and the API cannot answer")
        line("info", "embedding", f"{settings.embedding_provider}: {settings.embedding_model}")
        line("info", "llm", settings.llm_model)
        line("info", "pdf font repair", "on" if settings.pdf_font_repair else "off")
        exported = getattr(args, "exported_env", [])
        line("info", "env export", f"from .env: {', '.join(exported)} ({len(exported)})"
             if exported else "nothing exported from .env")

    deps_ok, rows = dependency_report()
    ok = ok and deps_ok
    for row in rows:
        line(*row)

    if settings is None:
        print("\nSome required checks failed.")
        return 1

    from rag_kit.step06_vector_store import (
        collection_dimension,
        collection_exists,
        describe_location,
        get_client,
    )
    collection = args.collection or settings.collection_name
    client = None
    try:
        client = get_client(create=False, settings=settings)
        if collection_exists(client, collection, settings):
            count = client.count(collection, exact=True).count
            dim = collection_dimension(client, collection)
            line("ok", "vector store", f"{describe_location(settings)}")
            line("ok", "collection", f"'{collection}': {count} vectors, dim {dim}")
            if args.deep:
                from rag_kit.step05_embedding import detect_dimension, get_embeddings
                model_dim = detect_dimension(get_embeddings(settings), settings)
                match = model_dim == dim
                ok = ok and match
                line("ok" if match else "FAIL", "embedding dimension",
                     f"model {model_dim} vs collection {dim}")
        else:
            line("warn", "collection", f"'{collection}' not found in "
                                       f"{describe_location(settings)} - run `ingest` first")
    except RagError as exc:
        line("warn", "vector store", str(exc))
    finally:
        if client is not None:
            client.close()

    if args.llm:
        try:
            from rag_kit.step10_generate import get_llm
            reply = get_llm(settings).invoke("Reply with the single word: ok").content
            line("ok", "llm call", f"{settings.llm_model} replied {str(reply).strip()[:30]!r}")
        except Exception as exc:
            ok = False
            line("FAIL", "llm call", str(exc)[:300])

    print("\nAll required checks passed." if ok else "\nSome required checks failed.")
    return 0 if ok else 1


# --- ingest ------------------------------------------------------------------
def cmd_ingest(args) -> int:
    files = args.files or [str(args.settings.pdf_path)]
    if args.recreate and len(files) > 1:
        print("--recreate with several files would keep only the last one; "
              "recreate once, then ingest the rest.", file=sys.stderr)
        return 2
    font_repair = {"on": True, "off": False}.get(args.font_repair)

    pipeline = _pipeline(args)
    failed = 0
    try:
        for file in files:
            print(f"--- INGEST {file} ".ljust(72, "-"), flush=True)
            try:
                report = pipeline.ingest(file, recreate=args.recreate, font_repair=font_repair)
                print(f"    -> {report['stored']} chunks from {report['pages']} "
                      f"page(s) in '{report['collection']}'")
            except RagError as exc:
                failed += 1
                print(f"error: {exc}", file=sys.stderr)
    finally:
        pipeline.close()

    if not failed:
        print('\nDone. Now ask something:  rag-kit ask "your question"')
    return 1 if failed else 0


# --- ask / search ------------------------------------------------------------
def _print_chunks(scored_docs, full: bool) -> None:
    for i, (doc, score) in enumerate(scored_docs, start=1):
        meta = doc.metadata
        print(f"\n[S{i}] score {score:.4f} | {meta.get('source_file')} | "
              f"page {meta.get('page_number') or '-'} | chunk {meta.get('chunk_id')} | "
              f"doc {meta.get('doc_id') or '-'}")
        text = doc.page_content if full else doc.page_content[:300] + "..."
        print("    " + text.replace("\n", "\n    "))


def cmd_ask(args) -> int:
    from rag_kit.step11_answer import present

    pipeline = _pipeline(args)
    out = sys.stdout

    def answer(question: str) -> None:
        with _quiet(args):
            result = pipeline.ask(question, k=args.top_k, min_score=args.min_score)
        if args.json:
            print(json.dumps({"question": result.question, "answer": result.answer,
                              "status": result.status, "sources": result.sources},
                             ensure_ascii=False, indent=2), file=out)
            return
        present(result.question, result.answer, result.scored_docs)
        if args.show_chunks:
            _print_chunks(result.scored_docs, full=True)

    try:
        if args.question:
            answer(" ".join(args.question))
            return 0
        print("Interactive mode. Type 'exit' to quit.")
        while True:
            try:
                question = input("\nYour question: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return 0
            if question.lower() in {"exit", "quit", "q"}:
                return 0
            if question:
                try:
                    answer(question)
                except RagError as exc:
                    print(f"error: {exc}", file=sys.stderr)
    finally:
        pipeline.close()


def cmd_search(args) -> int:
    pipeline = _pipeline(args)
    try:
        with _quiet(args):
            scored_docs = pipeline.search(" ".join(args.question), k=args.top_k,
                                          min_score=args.min_score)
    finally:
        pipeline.close()
    if args.json:
        from rag_kit.step11_answer import build_sources
        print(json.dumps(build_sources(scored_docs), ensure_ascii=False, indent=2))
    elif not scored_docs:
        print("No chunks retrieved.")
    else:
        _print_chunks(scored_docs, full=args.full)
    return 0


# --- documents / delete ------------------------------------------------------
def cmd_documents(args) -> int:
    pipeline = _pipeline(args)
    try:
        with _quiet(args):
            docs = pipeline.documents()
    finally:
        pipeline.close()
    if args.json:
        # Stable schema, documented in the README.
        print(json.dumps({
            "collection": pipeline.collection,
            "total_chunks": sum(docs.values()),
            "documents": [{"file": name, "chunks": count} for name, count in docs.items()],
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"Collection '{pipeline.collection}': {sum(docs.values())} chunks, {len(docs)} file(s)")
    for name, count in docs.items():
        print(f"  {count:6}  {name}")
    return 0


def cmd_delete(args) -> int:
    name = Path(args.file_name).name
    if not args.yes:
        reply = input(f"Delete every chunk of '{name}' from "
                      f"'{args.collection or args.settings.collection_name}'? [y/N] ")
        if reply.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1
    pipeline = _pipeline(args)
    try:
        removed = pipeline.delete(name)
    finally:
        pipeline.close()
    print(f"Removed {removed} chunks of '{name}'." if removed
          else f"No chunks found for '{name}'. `rag-kit documents` lists file names.")
    return 0


# --- serve / ui --------------------------------------------------------------
def _require(module: str, extra: str) -> bool:
    if importlib.util.find_spec(module) is None:
        print(f'error: {module} is not installed. Run: pip install "rag-kit[{extra}]"',
              file=sys.stderr)
        return False
    return True


def _child_env(args, what: str) -> dict:
    """Environment for the server process: this project (RAG_PROJECT_DIR) and,
    with --collection, COLLECTION_NAME for that process only (environment
    variables win over .env). .env is never edited."""
    collection = args.collection or args.settings.collection_name
    source = "--collection" if args.collection else "COLLECTION_NAME"
    print(f"{what} collection '{collection}' (from {source})", flush=True)
    env = {**os.environ, "RAG_PROJECT_DIR": str(args.settings.project_dir)}
    if args.collection:
        env["COLLECTION_NAME"] = args.collection
    return env


def cmd_serve(args) -> int:
    if not (_require("fastapi", "api") and _require("uvicorn", "api")):
        return 1
    env = _child_env(args, "Serving")
    # One worker: embedded Qdrant allows a single process.
    return subprocess.call([sys.executable, "-m", "uvicorn", "rag_kit.api:app",
                            "--host", args.host, "--port", str(args.port), "--workers", "1"],
                           env=env)


def cmd_ui(args) -> int:
    if not _require("streamlit", "ui"):
        return 1
    env = _child_env(args, "UI starts on")
    app = importlib.resources.files("rag_kit.ui").joinpath("app.py")
    with importlib.resources.as_file(app) as path:
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(path),
                                "--server.port", str(args.port)], env=env)


# --- argument parsing --------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag-kit", description="Standalone RAG toolkit.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", metavar="DIR",
                        help="project folder (default: RAG_PROJECT_DIR, else the nearest "
                             "folder with rag-kit.toml)")
    common.add_argument("--collection", help="Qdrant collection (default: COLLECTION_NAME)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", parents=[common], help="validate config, dependencies and store")
    p.add_argument("--deep", action="store_true",
                   help="also load the embedding model and compare its dimension")
    p.add_argument("--llm", action="store_true", help="also make one tiny LLM call (uses quota)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("ingest", parents=[common], help="index documents (.pdf, .txt, .md)")
    p.add_argument("files", nargs="*", help="files to ingest (default: PDF_PATH from .env)")
    p.add_argument("--recreate", action="store_true",
                   help="drop the whole collection first (after changing the embedding model)")
    p.add_argument("--font-repair", choices=["on", "off"],
                   help="override PDF_FONT_REPAIR for this run")
    p.set_defaults(func=cmd_ingest)

    for name, func, text in (("ask", cmd_ask, "answer a question with sources"),
                             ("search", cmd_search, "retrieval only - inspect chunks, no LLM")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("question", nargs="*" if name == "ask" else "+")
        p.add_argument("-k", "--top-k", type=int, help="chunks to retrieve (default: TOP_K)")
        p.add_argument("--min-score", type=float, help="drop chunks scoring below this")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "ask":
            p.add_argument("--show-chunks", action="store_true",
                           help="print the full text of every retrieved chunk")
        else:
            p.add_argument("--full", action="store_true", help="print full chunk text")
        p.set_defaults(func=func)

    p = sub.add_parser("documents", parents=[common], help="list indexed files")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_documents)

    p = sub.add_parser("delete", parents=[common], help="remove one file's chunks")
    p.add_argument("file_name", help="file name as shown by `documents`")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("serve", parents=[common], help="run the FastAPI service")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ui", parents=[common], help="run the Streamlit test UI")
    p.add_argument("--port", type=int, default=8501)
    p.set_defaults(func=cmd_ui)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    show_progress()  # step progress to stdout (stderr under --json, see _quiet)
    try:
        args.settings = Settings.load(project_dir=args.project)
    except RagError as exc:
        if args.command != "check":
            print(f"error: {exc}", file=sys.stderr)
            return 1
        args.settings, args.settings_error = None, exc  # `check` reports it
    else:
        set_default_settings(args.settings)
        # Before any command: HF_HOME, proxies etc. from .env must be in the
        # environment before Hugging Face is first imported. Child processes
        # (serve/ui) inherit them. See rag_kit/env.py for the allow-list.
        args.exported_env = export_env_file(args.settings)
    try:
        return args.func(args)
    except RagError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
