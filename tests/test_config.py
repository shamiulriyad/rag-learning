"""config.py: path resolution, defaults and validation."""

from pathlib import Path

import pytest

from rag.errors import RagError


def test_relative_qdrant_path_ignores_current_directory(load_config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config(QDRANT_PATH="./qdrant_data")
    assert config.QDRANT_PATH == config.BASE_DIR / "qdrant_data"
    assert not (tmp_path / "qdrant_data").exists()


def test_absolute_paths_are_kept(load_config, tmp_path):
    config = load_config(QDRANT_PATH=str(tmp_path / "store"), PDF_PATH=str(tmp_path / "a.pdf"))
    assert config.QDRANT_PATH == tmp_path / "store"
    assert config.PDF_PATH == tmp_path / "a.pdf"


def test_relative_pdf_path_resolves_from_project(load_config):
    config = load_config(PDF_PATH="data/book.pdf")
    assert config.PDF_PATH == config.BASE_DIR / "data" / "book.pdf"


def test_defaults_match_existing_bge_m3_index(load_config):
    config = load_config()
    assert config.EMBEDDING_PROVIDER == "huggingface"
    assert config.EMBEDDING_MODEL == "BAAI/bge-m3"
    assert config.COLLECTION_NAME == "pdf_rag"
    assert config.QDRANT_PATH is None
    assert config.PDF_FONT_REPAIR is False
    assert config.MIN_SCORE is None
    assert config.GOOGLE_API_KEY is None


def test_env_file_is_not_the_real_one(load_config):
    config = load_config()
    assert config.ENV_FILE.name == "empty_env.txt"


def test_missing_api_key_is_actionable(load_config):
    config = load_config()
    with pytest.raises(config.ConfigError, match="GOOGLE_API_KEY is not set"):
        config.require_api_key()
    assert issubclass(config.ConfigError, RagError)


def test_google_embeddings_require_key_up_front(load_config):
    config = load_config(EMBEDDING_PROVIDER="google")
    assert config.EMBEDDING_MODEL == "models/gemini-embedding-001"
    with pytest.raises(config.ConfigError, match="GOOGLE_API_KEY"):
        config.validate()


@pytest.mark.parametrize("env, message", [
    ({"EMBEDDING_PROVIDER": "openai"}, "EMBEDDING_PROVIDER must be"),
    ({"CHUNK_SIZE": "100", "CHUNK_OVERLAP": "100"}, "CHUNK_OVERLAP < CHUNK_SIZE"),
    ({"TOP_K": "0"}, "TOP_K must be at least 1"),
])
def test_validate_rejects_bad_settings(load_config, env, message):
    config = load_config(**env)
    with pytest.raises(config.ConfigError, match=message):
        config.validate()


def test_non_numeric_setting_fails_on_load(load_config):
    with pytest.raises(RagError, match="TOP_K must be a whole number"):
        load_config(TOP_K="four")


def test_bool_and_min_score_parsing(load_config):
    config = load_config(PDF_FONT_REPAIR="true", MIN_SCORE="0.35")
    assert config.PDF_FONT_REPAIR is True
    assert config.MIN_SCORE == pytest.approx(0.35)
    assert isinstance(config.BASE_DIR, Path)
