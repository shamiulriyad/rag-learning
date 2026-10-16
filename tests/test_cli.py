"""CLI behaviour, including how the project folder is found."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import rag_kit
from rag_kit import cli
from rag_kit.settings import PROJECT_MARKER, default_settings
from tests.conftest import ROOT


def _run(args, cwd, env_file, project=None):
    env = {k: v for k, v in os.environ.items() if k != "RAG_PROJECT_DIR"}
    env.update({"RAG_ENV_FILE": str(env_file), "PYTHONIOENCODING": "utf-8"})
    if project is not None:
        env["RAG_PROJECT_DIR"] = str(project)
    return subprocess.run([sys.executable, "-m", "rag_kit", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def _make_project(tmp_path, env_text=""):
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER).write_text("", encoding="utf-8")
    (project / ".env").write_text(env_text, encoding="utf-8")
    return project.resolve()


def test_help_works_from_another_directory(tmp_path):
    result = _run(["--help"], cwd=tmp_path, env_file=tmp_path / "none.env")
    assert result.returncode == 0
    assert "ingest" in result.stdout and "search" in result.stdout


def test_relative_store_path_is_resolved_from_the_project_not_cwd(tmp_path):
    project = _make_project(tmp_path, "QDRANT_PATH=./definitely_missing_store_for_tests\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _run(["documents"], cwd=elsewhere, env_file=project / ".env", project=project)

    assert result.returncode == 1
    assert "No local Qdrant store" in result.stderr
    assert str(project / "definitely_missing_store_for_tests") in result.stderr
    assert not (elsewhere / "definitely_missing_store_for_tests").exists()
    assert not (project / "definitely_missing_store_for_tests").exists()


def test_project_is_found_from_a_subfolder(tmp_path):
    project = _make_project(tmp_path, "QDRANT_PATH=./definitely_missing_store_for_tests\n")
    subfolder = project / "docs" / "notes"
    subfolder.mkdir(parents=True)

    result = _run(["documents"], cwd=subfolder, env_file=project / ".env")

    assert result.returncode == 1
    assert str(project / "definitely_missing_store_for_tests") in result.stderr
    assert not (subfolder / "definitely_missing_store_for_tests").exists()


def test_without_a_project_commands_fail_clearly_and_create_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    documents = _run(["documents"], cwd=empty, env_file=empty / "none.env")
    check = _run(["check"], cwd=empty, env_file=empty / "none.env")

    assert documents.returncode == 1
    assert "No rag-kit project found" in documents.stderr
    assert "--project" in documents.stderr and "RAG_PROJECT_DIR" in documents.stderr
    assert check.returncode == 1
    assert "Project     : not found" in check.stdout
    assert "langchain-core" in check.stdout  # the dependency report still runs
    assert list(empty.iterdir()) == []


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
            from rag_kit.step01_load_pdf import load_document
            load_document(path)

        def close(self):
            pass

    monkeypatch.setattr("rag_kit.pipeline.Pipeline", NoStore)
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

    monkeypatch.setattr("rag_kit.pipeline.Pipeline", EmptyQuestion)
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

    monkeypatch.setattr("rag_kit.pipeline.Pipeline", Noisy)
    assert cli.main(["search", "q", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["file"] == "a.md"
    assert "[9] Retrieved" in captured.err


def test_project_option_works_from_anywhere_and_beats_rag_project_dir(tmp_path):
    project = _make_project(tmp_path, "QDRANT_PATH=./definitely_missing_store_for_tests\n")
    other = tmp_path / "other"
    other.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _run(["documents", "--project", str(project)], cwd=elsewhere,
                  env_file=project / ".env", project=other)

    assert result.returncode == 1
    assert str(project / "definitely_missing_store_for_tests") in result.stderr
    assert list(elsewhere.iterdir()) == [] and list(other.iterdir()) == []


def test_project_option_needs_no_marker_but_must_exist(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    missing = tmp_path / "missing"

    ok = _run(["check", "--project", str(plain)], cwd=tmp_path, env_file=plain / ".env")
    bad = _run(["documents", "--project", str(missing)], cwd=tmp_path, env_file=plain / ".env")

    assert f"Project     : {plain.resolve()}" in ok.stdout
    assert bad.returncode == 1 and "does not exist" in bad.stderr
    assert not missing.exists()


# --- dependency check: derived from the package metadata (pyproject extras) -----


def test_requirement_groups_reads_extras_and_skips_self_references():
    requirements = [
        "langchain-core<2,>=1.6.9",
        'fastapi<1,>=0.143; extra == "api"',
        'rag-kit[api]; extra == "dev"',
        'pytest<10,>=9.1; extra == "dev"',
        'tomli>=2; python_version < "3.0"',
        'typing-extensions>=4; python_version >= "3.8"',
        'streamlit<2,>=1.65; extra == "ui"',
    ]
    assert cli.requirement_groups(requirements) == [
        ("langchain-core", None), ("fastapi", "api"), ("pytest", "dev"),
        ("typing-extensions", None), ("streamlit", "ui"),
    ]


def test_dependency_report_covers_every_declared_requirement():
    declared = cli.requirement_groups(importlib.metadata.requires("rag-kit"))
    _ok, rows = cli.dependency_report()
    names = {name for _status, name, _detail in rows}

    assert {extra for _name, extra in declared} == {None, "local", "gemini", "api", "ui", "dev"}
    for name, extra in declared:
        assert name in names, f"{name} ({extra or 'core'}) is not checked"


def test_missing_core_dependency_fails():
    ok, rows = cli.dependency_report(["pytest", "no-such-package-xyz>=1"])
    assert not ok
    assert ("FAIL", "no-such-package-xyz", "not installed (core): pip install rag-kit") in rows
    assert rows[0][0] == "ok" and rows[0][1] == "pytest"


def test_missing_optional_dependency_only_warns():
    ok, rows = cli.dependency_report(["pytest", 'no-such-package-xyz; extra == "api"'])
    assert ok
    assert ("--", "no-such-package-xyz",
            'not installed (optional: serve): pip install "rag-kit[api]"') in rows


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
    assert env["RAG_PROJECT_DIR"] == str(ROOT)
    assert os.environ.get("COLLECTION_NAME") == before  # this process is untouched
    assert default_settings().collection_name == "pdf_rag"
    assert "collection 'experiments' (from --collection)" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["serve", "ui"])
def test_server_commands_default_to_configured_collection(command, captured_launch, capsys):
    assert cli.main([command]) == 0
    [(cmd, env)] = captured_launch
    # The child gets this project; COLLECTION_NAME is left to .env / the environment.
    assert env["RAG_PROJECT_DIR"] == str(ROOT)
    assert env.get("COLLECTION_NAME") == os.environ.get("COLLECTION_NAME")
    assert "collection 'pdf_rag' (from COLLECTION_NAME)" in capsys.readouterr().out


def test_server_commands_pass_the_chosen_project_to_the_child(tmp_path, captured_launch):
    project = _make_project(tmp_path)
    assert cli.main(["serve", "--project", str(project)]) == 0
    [(_cmd, env)] = captured_launch
    assert env["RAG_PROJECT_DIR"] == str(project)


def test_serve_runs_the_packaged_app(captured_launch):
    assert cli.main(["serve", "--port", "8123"]) == 0
    [(cmd, _env)] = captured_launch
    assert cmd[1:4] == ["-m", "uvicorn", "rag_kit.api:app"]
    assert cmd[cmd.index("--port") + 1] == "8123"
    assert cmd[-2:] == ["--workers", "1"]


def test_ui_runs_the_packaged_streamlit_app(captured_launch):
    assert cli.main(["ui"]) == 0
    [(cmd, _env)] = captured_launch
    assert cmd[1:4] == ["-m", "streamlit", "run"]
    app = Path(cmd[4])
    assert app.is_file() and app.name == "app.py"
    assert Path(rag_kit.__file__).resolve().parent / "ui" == app.resolve().parent


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

    monkeypatch.setattr("rag_kit.pipeline.Pipeline", TwoDocs)
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
    options = {opt for action in subparsers.choices[command]._actions
               for opt in action.option_strings}
    assert {"--project", "--collection"} <= options


# --- check: hint when the project's .env does not exist yet ----------------------


def _check_without_env_override(project):
    env = {k: v for k, v in os.environ.items() if k not in ("RAG_ENV_FILE", "RAG_PROJECT_DIR")}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", "rag_kit", "check"], cwd=project, env=env,
                          capture_output=True, text=True, timeout=120)


def test_check_explains_how_to_create_env_from_the_example(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER).write_text("", encoding="utf-8")
    (project / ".env.example").write_text("GOOGLE_API_KEY=\n", encoding="utf-8")

    result = _check_without_env_override(project)

    assert "[warn] .env" in result.stdout
    assert "cp .env.example .env" in result.stdout
    assert "Copy-Item .env.example .env" in result.stdout
    assert "Qdrant server at http://localhost:6333" in result.stdout
    assert not (project / ".env").exists()  # check never creates it


def test_check_without_env_or_example_points_to_the_readme(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER).write_text("", encoding="utf-8")

    result = _check_without_env_override(project)

    assert "Create .env in" in result.stdout and "cp .env.example" not in result.stdout
    assert not (project / ".env").exists()


def test_check_has_no_env_hint_when_env_exists(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER).write_text("", encoding="utf-8")
    (project / ".env").write_text("QDRANT_PATH=qdrant_data\n", encoding="utf-8")

    result = _check_without_env_override(project)

    assert "[warn] .env" not in result.stdout
    assert "(found)" in result.stdout
