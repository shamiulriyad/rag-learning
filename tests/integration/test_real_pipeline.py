"""Integration tests against the real .env, embedding model and Qdrant store.

Off by default. They run the CLI in a subprocess so the real configuration is
used, not the unit-test one:

    RAG_RUN_INTEGRATION=1 python -m pytest -m integration      # model + local store
    RAG_RUN_INTEGRATION=1 RAG_RUN_GEMINI=1 python -m pytest -m "integration or gemini"

Safety: retrieval against COLLECTION_NAME is read-only. Ingestion goes into a
uniquely named `pytest_ingest_*` collection inside a temporary Qdrant directory,
so the real store is never written to. Nothing here uses --recreate. Stop
`serve` / `ui` first - local Qdrant allows one process.
"""

import json
import os
import re
import subprocess
import sys
import uuid

import pytest

from tests.conftest import ROOT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RAG_RUN_INTEGRATION") != "1",
                       reason="set RAG_RUN_INTEGRATION=1 to run integration tests"),
]


def run_cli(*args, cwd=ROOT, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RAG_ENV_FILE", "RAG_API_WARMUP")}
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra_env or {})  # real env vars take priority over .env
    return subprocess.run([sys.executable, str(ROOT / "cli.py"), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=900)


def test_retrieval_from_existing_collection_is_read_only(tmp_path):
    before = run_cli("documents")
    assert before.returncode == 0, before.stderr

    # From a different working directory, to prove paths do not depend on cwd.
    result = run_cli("search", "What is a countable noun?", "-k", "3", "--json", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    sources = json.loads(result.stdout)
    assert len(sources) == 3
    assert all(s["page"] and s["file"] and s["score"] > 0 for s in sources)

    assert run_cli("documents").stdout == before.stdout  # unchanged


def test_fresh_ingestion_into_separate_collection(tmp_path):
    collection = f"pytest_ingest_{uuid.uuid4().hex[:8]}"
    store = {"QDRANT_PATH": str(tmp_path / "qdrant_test")}
    doc = tmp_path / "toolkit_notes.md"
    doc.write_text(
        "# Qdrant notes\n\n" + "\n\n".join(
            f"Section {i}: the toolkit stores chunk vectors in Qdrant and cites page numbers. "
            "Re-ingesting a file replaces its earlier chunks instead of duplicating them."
            for i in range(10)),
        encoding="utf-8")

    def cli(*args):
        result = run_cli(*args, "--collection", collection, extra_env=store)
        assert result.returncode == 0, result.stderr
        return result

    def chunk_count():
        listing = cli("documents").stdout
        assert "toolkit_notes.md" in listing
        return int(listing.split(":")[1].split()[0])

    cli("ingest", str(doc))
    after_first = chunk_count()
    assert after_first >= 1

    cli("ingest", str(doc))
    assert chunk_count() == after_first  # replaced, not duplicated

    sources = json.loads(cli("search", "How does re-ingesting work?", "-k", "2", "--json").stdout)
    assert sources and sources[0]["file"] == "toolkit_notes.md"


@pytest.mark.gemini
@pytest.mark.skipif(os.getenv("RAG_RUN_GEMINI") != "1",
                    reason="set RAG_RUN_GEMINI=1 to make a real Gemini call (uses quota)")
def test_real_gemini_answer():
    result = run_cli("ask", "What is a countable noun?", "-k", "3", "--json")
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "answered"
    assert body["answer"].strip()

    # Source attribution: every [S#] marker in the answer maps to a returned
    # source with a file and page, and at least one marker is present.
    sources = {s["marker"]: s for s in body["sources"]}
    assert len(sources) == 3
    cited = set(re.findall(r"\[(S\d+)\]", body["answer"]))
    assert cited, f"answer has no [S#] markers: {body['answer']!r}"
    assert cited <= set(sources), f"answer cites unknown sources: {cited - set(sources)}"
    for marker in cited:
        assert sources[marker]["file"] and sources[marker]["page"]
