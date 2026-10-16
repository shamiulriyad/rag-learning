"""rag/env.py: which .env keys reach os.environ, and who exports them."""

import logging
import os
import subprocess
import sys

import pytest

from rag.env import export_env_file
from rag.settings import Settings
from tests.conftest import ROOT

SECRET = "secret-value-must-never-appear"

ENV_TEXT = f"""
GOOGLE_API_KEY={SECRET}-google
QDRANT_API_KEY={SECRET}-qdrant
COLLECTION_NAME=from_env_file
RAG_API_WARMUP=0
HF_HOME=/tmp/hf-home
HF_TOKEN={SECRET}-hf
TRANSFORMERS_OFFLINE=1
SENTENCE_TRANSFORMERS_HOME=/tmp/st
TORCH_HOME=/tmp/torch
TOKENIZERS_PARALLELISM=false
https_proxy=http://proxy.local:8080
NO_PROXY=localhost
SSL_CERT_FILE=/tmp/ca.pem
MY_TOOL_TOKEN={SECRET}-tool
EMPTY_HF_LIKE=
HF_ENDPOINT=
"""


@pytest.fixture
def settings(tmp_path) -> Settings:
    (tmp_path / ".env").write_text(ENV_TEXT, encoding="utf-8")
    return Settings.load(tmp_path, environ={})


def test_exports_only_the_allow_list(settings):
    environ = {}
    exported = export_env_file(settings, environ)

    assert exported == sorted([
        "HF_HOME", "HF_TOKEN", "NO_PROXY", "SENTENCE_TRANSFORMERS_HOME", "SSL_CERT_FILE",
        "TOKENIZERS_PARALLELISM", "TORCH_HOME", "TRANSFORMERS_OFFLINE", "https_proxy",
    ])
    assert set(environ) == set(exported)
    assert environ["HF_HOME"] == "/tmp/hf-home"


@pytest.mark.parametrize("name", ["GOOGLE_API_KEY", "QDRANT_API_KEY", "COLLECTION_NAME",
                                  "RAG_API_WARMUP", "MY_TOOL_TOKEN"])
def test_rag_kit_settings_and_unknown_keys_are_not_exported(settings, name):
    environ = {}
    export_env_file(settings, environ)
    assert name not in environ


def test_empty_values_are_skipped(settings):
    environ = {}
    export_env_file(settings, environ)
    assert "HF_ENDPOINT" not in environ and "EMPTY_HF_LIKE" not in environ


@pytest.mark.parametrize("where", ["env_file", "process"])
def test_rag_export_env_opts_in_extra_names(tmp_path, where):
    text = ENV_TEXT + ("RAG_EXPORT_ENV=MY_TOOL_TOKEN, OTHER\n" if where == "env_file" else "")
    (tmp_path / ".env").write_text(text, encoding="utf-8")
    environ = {"RAG_EXPORT_ENV": "MY_TOOL_TOKEN"} if where == "process" else {}

    export_env_file(Settings.load(tmp_path, environ={}), environ)

    assert environ["MY_TOOL_TOKEN"] == f"{SECRET}-tool"
    assert "OTHER" not in environ  # listed but not present in .env


def test_rag_export_env_cannot_export_rag_kit_settings(tmp_path, caplog):
    (tmp_path / ".env").write_text(
        ENV_TEXT + "RAG_EXPORT_ENV=GOOGLE_API_KEY,QDRANT_API_KEY,RAG_PROJECT_DIR\n",
        encoding="utf-8")
    environ = {}
    with caplog.at_level(logging.WARNING, logger="rag"):
        export_env_file(Settings.load(tmp_path, environ={}), environ)

    assert "GOOGLE_API_KEY" not in environ and "QDRANT_API_KEY" not in environ
    assert "never exported: GOOGLE_API_KEY, QDRANT_API_KEY, RAG_PROJECT_DIR" in caplog.text
    assert SECRET not in caplog.text


def test_process_environment_wins_unless_override(settings):
    environ = {"HF_HOME": "/already/set"}
    assert "HF_HOME" not in export_env_file(settings, environ)
    assert environ["HF_HOME"] == "/already/set"

    assert "HF_HOME" in export_env_file(settings, environ, override=True)
    assert environ["HF_HOME"] == "/tmp/hf-home"


def test_values_are_never_logged_or_returned(settings, caplog):
    environ = {}
    with caplog.at_level(logging.DEBUG):
        exported = export_env_file(settings, environ)
    assert SECRET not in caplog.text
    assert all(SECRET not in name for name in exported)


def test_second_call_exports_nothing_new(settings):
    environ = {}
    export_env_file(settings, environ)
    assert export_env_file(settings, environ) == []


def test_loading_settings_still_exports_nothing(settings):
    before = dict(os.environ)
    Settings.load(settings.project_dir)
    assert dict(os.environ) == before


def test_missing_env_file_exports_nothing(tmp_path):
    assert export_env_file(Settings.load(tmp_path, environ={}), {}) == []


# --- entry points ------------------------------------------------------------------


def test_cli_exports_allow_list_and_never_prints_values(tmp_path):
    env_file = tmp_path / "cli.env"
    env_file.write_text(ENV_TEXT + "QDRANT_PATH=./missing_store_for_env_test\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("HF_", "TRANSFORMERS_", "RAG_")) and k.upper() not in
           {"HTTPS_PROXY", "NO_PROXY", "GOOGLE_API_KEY"}}
    env.update({"RAG_ENV_FILE": str(env_file), "PYTHONIOENCODING": "utf-8"})

    result = subprocess.run([sys.executable, str(ROOT / "cli.py"), "check"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=120)

    output = result.stdout + result.stderr
    assert "env export" in output and "HF_HOME" in output and "https_proxy" in output
    assert "MY_TOOL_TOKEN" not in output
    assert SECRET not in output
    assert not (ROOT / "missing_store_for_env_test").exists()


@pytest.fixture
def restore_environ():
    before = dict(os.environ)
    yield
    for name in set(os.environ) - set(before):
        del os.environ[name]
    os.environ.update(before)


def test_default_api_app_exports_at_startup_but_custom_apps_do_not(settings, restore_environ,
                                                                   monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import main

    for name in ("HF_HOME", "SSL_CERT_FILE", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    with TestClient(main.create_app(settings=settings)):
        assert "HF_HOME" not in os.environ

    with TestClient(main.create_app(settings=settings, export_env=True)):
        assert os.environ["HF_HOME"] == "/tmp/hf-home"
        assert "GOOGLE_API_KEY" not in os.environ

    assert main.app.state.export_env is True  # the default app is the exporting one
