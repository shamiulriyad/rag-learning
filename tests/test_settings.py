"""rag.settings.Settings: loading without side effects, explicit injection."""

import os
from pathlib import Path

import pytest

from rag.errors import ConfigError
from rag.pipeline import Pipeline
from rag.settings import Settings
from tests.conftest import make_text_file


def _write_env(tmp_path: Path, text: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def test_reads_project_env_and_resolves_paths_from_project(tmp_path, monkeypatch):
    _write_env(tmp_path, "QDRANT_PATH=store\nPDF_PATH=data/a.pdf\nTOP_K=7\n")
    monkeypatch.chdir(tmp_path.parent)  # cwd must not matter

    settings = Settings.load(tmp_path, environ={})

    assert settings.project_dir == tmp_path.resolve()
    assert settings.env_file == tmp_path / ".env"
    assert settings.qdrant_path == tmp_path.resolve() / "store"
    assert settings.pdf_path == tmp_path.resolve() / "data" / "a.pdf"
    assert settings.top_k == 7


def test_environment_wins_over_env_file_and_empty_means_unset(tmp_path):
    _write_env(tmp_path, "COLLECTION_NAME=from_file\nTOP_K=9\nLLM_MODEL=from-file\n")
    settings = Settings.load(tmp_path, environ={"COLLECTION_NAME": "from_env", "TOP_K": ""})
    assert settings.collection_name == "from_env"
    assert settings.top_k == 4                      # empty value falls back to the default
    assert settings.llm_model == "from-file"


def test_rag_env_file_points_at_another_file(tmp_path):
    other = tmp_path / "custom.env"
    other.write_text("COLLECTION_NAME=custom\n", encoding="utf-8")
    settings = Settings.load(tmp_path, environ={"RAG_ENV_FILE": str(other)})
    assert settings.env_file == other and settings.collection_name == "custom"


def test_loading_does_not_modify_os_environ(tmp_path):
    _write_env(tmp_path, "RAG_TEST_ONLY_SETTING=1\nCOLLECTION_NAME=from_file\n")
    before = dict(os.environ)
    Settings.load(tmp_path)
    assert dict(os.environ) == before


def test_defaults_match_existing_bge_m3_index(tmp_path):
    settings = Settings.load(tmp_path, environ={})
    assert settings.embedding_provider == "huggingface"
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.collection_name == "pdf_rag"
    assert settings.qdrant_path is None and settings.min_score is None
    assert settings.embed_sleep == 0


def test_google_provider_defaults(tmp_path):
    settings = Settings.load(tmp_path, environ={"EMBEDDING_PROVIDER": "Google"})
    assert settings.embedding_provider == "google"
    assert settings.embedding_model == "models/gemini-embedding-001"
    assert settings.embed_sleep == 60
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        settings.validate()


def test_secrets_are_not_in_repr(tmp_path):
    settings = Settings.load(tmp_path, environ={"GOOGLE_API_KEY": "secret-google-value",
                                                "QDRANT_API_KEY": "secret-qdrant-value"})
    assert settings.google_api_key == "secret-google-value"
    assert "secret-" not in repr(settings)


def test_invalid_number_is_reported_on_load(tmp_path):
    with pytest.raises(ConfigError, match="CHUNK_SIZE must be a whole number"):
        Settings.load(tmp_path, environ={"CHUNK_SIZE": "big"})


def test_replace_returns_a_new_object(tmp_path):
    settings = Settings.load(tmp_path, environ={})
    changed = settings.replace(collection_name="other")
    assert changed.collection_name == "other" and settings.collection_name == "pdf_rag"


def test_pipeline_uses_injected_settings(tmp_path, fake_embeddings, memory_client):
    settings = Settings.load(tmp_path, environ={"COLLECTION_NAME": "injected", "TOP_K": "1",
                                                "CHUNK_SIZE": "200", "CHUNK_OVERLAP": "20"})
    pipeline = Pipeline(settings=settings, embeddings=fake_embeddings, client=memory_client)
    report = pipeline.ingest(make_text_file(tmp_path, "notes.txt", paragraphs=6))

    assert pipeline.collection == "injected" and report["collection"] == "injected"
    assert report["stored"] > 3                      # chunk_size 200, not the default 1000
    assert len(pipeline.search("noun")) == 1        # top_k 1
