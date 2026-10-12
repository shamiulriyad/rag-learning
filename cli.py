"""Command-line interface for the RAG toolkit.

    python cli.py check [--deep] [--llm]      validate config, dependencies, store
    python cli.py ingest FILE [FILE ...]      steps 1-6 (re-ingesting replaces)
    python cli.py ask "question"              steps 7-11 (no question = interactive)
    python cli.py search "question"           retrieval only, no LLM call
    python cli.py documents                   files in the collection + chunk counts
    python cli.py delete FILE_NAME            remove one document's chunks
    python cli.py serve                       FastAPI service (needs requirements-api.txt)
    python cli.py ui                          Streamlit test UI (needs requirements-ui.txt)

Works from any directory: paths in .env are resolved from this folder.
Every command takes --collection to work on something other than COLLECTION_NAME.
"""

import argparse
import contextlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import config
from rag.errors import RagError

ROOT = Path(__file__).resolve().parent


def _pipeline(args):
    from rag.pipeline import Pipeline
    return Pipeline(collection=args.collection)


def _quiet(args):
    """With --json, step progress goes to stderr so stdout is only the JSON."""
    if getattr(args, "json", False):
        return contextlib.redirect_stdout(sys.stderr)
    return contextlib.nullcontext()


# --- check -------------------------------------------------------------------
def cmd_check(args) -> int:
    ok = True

    def line(status: str, label: str, detail: str = "") -> None:
        print(f"  [{status:^4}] {label:<22} {detail}")

    print(f"Config file : {config.ENV_FILE} ({'found' if config.ENV_FILE.exists() else 'MISSING'})")
    print(f"Python      : {sys.version.split()[0]}")
    try:
        config.validate()
        line("ok", "settings", f"chunk {config.CHUNK_SIZE}/{config.CHUNK_OVERLAP}, "
                               f"top_k {config.TOP_K}")
    except RagError as exc:
        ok = False
        line("FAIL", "settings", str(exc))

    line("ok" if config.GOOGLE_API_KEY else "warn", "GOOGLE_API_KEY",
         "set" if config.GOOGLE_API_KEY else "missing - `ask` and the API cannot answer")
    line("info", "embedding", f"{config.EMBEDDING_PROVIDER}: {config.EMBEDDING_MODEL}")
    line("info", "llm", config.LLM_MODEL)
    line("info", "pdf font repair", "on" if config.PDF_FONT_REPAIR else "off")

    modules = {"pymupdf": "core", "langchain_qdrant": "core", "langchain_google_genai": "core",
               "langchain_huggingface": "huggingface embeddings",
               "sentence_transformers": "huggingface embeddings",
               "fastapi": "optional: serve", "uvicorn": "optional: serve",
               "streamlit": "optional: ui", "pytest": "optional: tests"}
    for module, purpose in modules.items():
        found = importlib.util.find_spec(module) is not None
        required = purpose == "core" or (purpose.startswith("huggingface")
                                         and config.EMBEDDING_PROVIDER == "huggingface")
        if not found and required:
            ok = False
        line("ok" if found else ("FAIL" if required else "--"), module,
             purpose if found else f"not installed ({purpose})")

    from rag.step06_vector_store import (collection_dimension, collection_exists,
                                         describe_location, get_client)
    collection = args.collection or config.COLLECTION_NAME
    client = None
    try:
        client = get_client(create=False)
        if collection_exists(client, collection):
            count = client.count(collection, exact=True).count
            dim = collection_dimension(client, collection)
            line("ok", "vector store", f"{describe_location()}")
            line("ok", "collection", f"'{collection}': {count} vectors, dim {dim}")
            if args.deep:
                from rag.step05_embedding import detect_dimension, get_embeddings
                model_dim = detect_dimension(get_embeddings())
                match = model_dim == dim
                ok = ok and match
                line("ok" if match else "FAIL", "embedding dimension",
                     f"model {model_dim} vs collection {dim}")
        else:
            line("warn", "collection", f"'{collection}' not found in {describe_location()} "
                                       "- run `ingest` first")
    except RagError as exc:
        line("warn", "vector store", str(exc))
    finally:
        if client is not None:
            client.close()

    if args.llm:
        try:
            from rag.step10_generate import get_llm
            reply = get_llm().invoke("Reply with the single word: ok").content
            line("ok", "llm call", f"{config.LLM_MODEL} replied {str(reply).strip()[:30]!r}")
        except Exception as exc:
            ok = False
            line("FAIL", "llm call", str(exc)[:300])

    print("\nAll required checks passed." if ok else "\nSome required checks failed.")
    return 0 if ok else 1


# --- ingest ------------------------------------------------------------------
def cmd_ingest(args) -> int:
    files = args.files or ([args.pdf] if args.pdf else [str(config.PDF_PATH)])
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
        print('\nDone. Now ask something:  python cli.py ask "your question"')
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
    from rag.step11_answer import present

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
        from rag.step11_answer import build_sources
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
        docs = pipeline.documents()
    finally:
        pipeline.close()
    print(f"Collection '{pipeline.collection}': {sum(docs.values())} chunks, {len(docs)} file(s)")
    for name, count in docs.items():
        print(f"  {count:6}  {name}")
    return 0


def cmd_delete(args) -> int:
    name = Path(args.file_name).name
    if not args.yes:
        reply = input(f"Delete every chunk of '{name}' from "
                      f"'{args.collection or config.COLLECTION_NAME}'? [y/N] ")
        if reply.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1
    pipeline = _pipeline(args)
    try:
        removed = pipeline.delete(name)
    finally:
        pipeline.close()
    print(f"Removed {removed} chunks of '{name}'." if removed
          else f"No chunks found for '{name}'. `python cli.py documents` lists file names.")
    return 0


# --- serve / ui --------------------------------------------------------------
def _require(module: str, requirements: str) -> bool:
    if importlib.util.find_spec(module) is None:
        print(f"error: {module} is not installed. Run: pip install -r {requirements}",
              file=sys.stderr)
        return False
    return True


def cmd_serve(args) -> int:
    if not (_require("fastapi", "requirements-api.txt") and
            _require("uvicorn", "requirements-api.txt")):
        return 1
    if args.collection:
        print("note: --collection is ignored by `serve`; set COLLECTION_NAME instead.")
    # One worker: embedded Qdrant allows a single process.
    return subprocess.call([sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(ROOT),
                            "--host", args.host, "--port", str(args.port), "--workers", "1"])


def cmd_ui(args) -> int:
    if not _require("streamlit", "requirements-ui.txt"):
        return 1
    if args.collection:
        print("note: --collection is ignored by `ui`; pick the collection in the sidebar.")
    return subprocess.call([sys.executable, "-m", "streamlit", "run",
                            str(ROOT / "streamlit_app.py"), "--server.port", str(args.port)])


# --- argument parsing --------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Standalone RAG toolkit.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--collection", help=f"Qdrant collection (default: {config.COLLECTION_NAME})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", parents=[common], help="validate config, dependencies and store")
    p.add_argument("--deep", action="store_true",
                   help="also load the embedding model and compare its dimension")
    p.add_argument("--llm", action="store_true", help="also make one tiny LLM call (uses quota)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("ingest", parents=[common], help="index documents (.pdf, .txt, .md)")
    p.add_argument("files", nargs="*", help="files to ingest (default: PDF_PATH from .env)")
    p.add_argument("--pdf", help=argparse.SUPPRESS)  # original ingest.py flag
    p.add_argument("--recreate", action="store_true",
                   help="drop the whole collection first (after changing the embedding model)")
    p.add_argument("--font-repair", choices=["on", "off"],
                   help="override PDF_FONT_REPAIR for this run")
    p.set_defaults(func=cmd_ingest)

    for name, func, text in (("ask", cmd_ask, "answer a question with sources"),
                             ("search", cmd_search, "retrieval only - inspect chunks, no LLM")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("question", nargs="*" if name == "ask" else "+")
        p.add_argument("-k", "--top-k", type=int, help=f"chunks to retrieve (default {config.TOP_K})")
        p.add_argument("--min-score", type=float, help="drop chunks scoring below this")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "ask":
            p.add_argument("--show-chunks", action="store_true",
                           help="print the full text of every retrieved chunk")
        else:
            p.add_argument("--full", action="store_true", help="print full chunk text")
        p.set_defaults(func=func)

    p = sub.add_parser("documents", parents=[common], help="list indexed files")
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
