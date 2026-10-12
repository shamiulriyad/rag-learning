"""CLI behaviour, including running from a different working directory."""

import json
import os
import subprocess
import sys

import pytest

import cli
from tests.conftest import ROOT


def _run(args, cwd, env_file):
    env = {**os.environ, "RAG_ENV_FILE": str(env_file), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(ROOT / "cli.py"), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def test_help_works_from_another_directory(tmp_path):
    result = _run(["--help"], cwd=tmp_path, env_file=tmp_path / "none.env")
    assert result.returncode == 0
    assert "ingest" in result.stdout and "search" in result.stdout


def test_relative_store_path_is_not_created_in_cwd(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("QDRANT_PATH=./definitely_missing_store_for_tests\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _run(["documents"], cwd=elsewhere, env_file=env_file)

    assert result.returncode == 1
    assert "No local Qdrant store" in result.stderr
    assert str(ROOT) in result.stderr  # resolved from the project, not the cwd
    assert not (elsewhere / "definitely_missing_store_for_tests").exists()
    assert not (ROOT / "definitely_missing_store_for_tests").exists()


def test_recreate_refuses_multiple_files(capsys):
    assert cli.main(["ingest", "a.pdf", "b.pdf", "--recreate"]) == 2
    assert "--recreate with several files" in capsys.readouterr().err


def test_ingest_reports_unsupported_file(tmp_path, capsys, monkeypatch):
    # Fails in step 1, before any model or store is opened.
    bad = tmp_path / "data.xlsx"
    bad.write_bytes(b"x")

    class NoStore:
        def __init__(self, *a, **kw):
            pass

        def ingest(self, path, **kw):
            from rag.step01_load_pdf import load_document
            load_document(path)

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", NoStore)
    assert cli.main(["ingest", str(bad)]) == 1
    assert "Unsupported file type '.xlsx'" in capsys.readouterr().err


def test_ask_rejects_empty_question_via_pipeline(monkeypatch, capsys):
    class EmptyQuestion:
        def __init__(self, *a, **kw):
            pass

        def ask(self, question, **kw):
            raise ValueError("Question is empty.")

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", EmptyQuestion)
    assert cli.main(["ask", " "]) == 2
    assert "Question is empty" in capsys.readouterr().err


def test_json_mode_keeps_stdout_pure(monkeypatch, capsys):
    from langchain_core.documents import Document

    class Noisy:
        def __init__(self, *a, **kw):
            pass

        def search(self, question, **kw):
            print("[9] Retrieved  : 1 chunks")  # step progress, like the real pipeline
            return [(Document(page_content="t", metadata={"source_file": "a.md"}), 0.5)]

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", Noisy)
    assert cli.main(["search", "q", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["file"] == "a.md"
    assert "[9] Retrieved" in captured.err


@pytest.mark.parametrize("command", ["check", "ingest", "ask", "search", "documents",
                                     "delete", "serve", "ui"])
def test_every_documented_command_exists(command):
    parser = cli.build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")
    assert command in subparsers.choices
