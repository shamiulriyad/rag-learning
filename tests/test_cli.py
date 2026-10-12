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


# --- dependency check: derived from the requirements files ---------------------


def test_requirement_names_parses_real_world_lines(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("# comment\n-r base.txt\n\nuvicorn[standard]>=0.30.0\n"
                   "langchain-core>=0.3.0  # inline\nqdrant_client==1.9\n", encoding="utf-8")
    assert cli.requirement_names(req) == ["uvicorn", "langchain-core", "qdrant_client"]


def test_dependency_report_covers_every_requirements_file():
    _ok, rows = cli.dependency_report()
    names = {name for _status, name, _detail in rows}
    for file in cli.REQUIREMENT_FILES:
        for name in cli.requirement_names(ROOT / file):
            assert name in names, f"{name} from {file} is not checked"


def _fake_project(tmp_path, core, api=""):
    (tmp_path / "requirements.txt").write_text(core, encoding="utf-8")
    (tmp_path / "requirements-api.txt").write_text(f"-r requirements.txt\n{api}", encoding="utf-8")
    (tmp_path / "requirements-ui.txt").write_text("", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("", encoding="utf-8")
    return tmp_path


def test_missing_core_dependency_fails(tmp_path):
    root = _fake_project(tmp_path, "pytest\nno-such-package-xyz>=1\n")
    ok, rows = cli.dependency_report(root)
    assert not ok
    assert ("FAIL", "no-such-package-xyz",
            "not installed (core): pip install -r requirements.txt") in rows
    assert rows[0][0] == "ok" and rows[0][1] == "pytest"


def test_missing_optional_dependency_only_warns(tmp_path):
    root = _fake_project(tmp_path, "pytest\n", api="no-such-package-xyz\n")
    ok, rows = cli.dependency_report(root)
    assert ok
    assert ("--", "no-such-package-xyz",
            "not installed (optional: serve): pip install -r requirements-api.txt") in rows


# --- serve / ui honour --collection for the child process only ------------------


@pytest.fixture
def captured_launch(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_require", lambda *a: True)
    monkeypatch.setattr(cli.subprocess, "call",
                        lambda cmd, env=None: calls.append((cmd, env)) or 0)
    return calls


@pytest.mark.parametrize("command", ["serve", "ui"])
def test_server_commands_pass_collection_to_child_only(command, captured_launch, capsys):
    before = os.environ.get("COLLECTION_NAME")
    assert cli.main([command, "--collection", "experiments"]) == 0

    [(cmd, env)] = captured_launch
    assert env["COLLECTION_NAME"] == "experiments"
    assert os.environ.get("COLLECTION_NAME") == before  # this process is untouched
    assert cli.config.COLLECTION_NAME == "pdf_rag"
    assert "collection 'experiments' (from --collection)" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["serve", "ui"])
def test_server_commands_default_to_configured_collection(command, captured_launch, capsys):
    assert cli.main([command]) == 0
    [(cmd, env)] = captured_launch
    assert env is None  # inherits the environment; .env decides
    assert "collection 'pdf_rag' (from COLLECTION_NAME)" in capsys.readouterr().out


# --- documents --json -------------------------------------------------------------


def test_documents_json_schema(monkeypatch, capsys):
    class TwoDocs:
        collection = "pdf_rag"

        def __init__(self, *a, **kw):
            pass

        def documents(self):
            return {"a.pdf": 3, "b.md": 1}

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", TwoDocs)
    assert cli.main(["documents", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "collection": "pdf_rag",
        "total_chunks": 4,
        "documents": [{"file": "a.pdf", "chunks": 3}, {"file": "b.md", "chunks": 1}],
    }


@pytest.mark.parametrize("command", ["check", "ingest", "ask", "search", "documents",
                                     "delete", "serve", "ui"])
def test_every_documented_command_exists(command):
    parser = cli.build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")
    assert command in subparsers.choices
