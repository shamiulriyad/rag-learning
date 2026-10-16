"""rag_kit.settings.Settings: loading without side effects, discovery, explicit injection."""

import os
from pathlib import Path

import pytest

from rag_kit.errors import ConfigError, RagError
from rag_kit.pipeline import Pipeline
from rag_kit.settings import PROJECT_MARKER, Settings, find_project_dir
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


def test_absolute_paths_are_kept(tmp_path):
    settings = Settings.load(tmp_path, environ={"QDRANT_PATH": str(tmp_path / "store"),
                                                "PDF_PATH": str(tmp_path / "a.pdf")})
    assert settings.qdrant_path == tmp_path / "store"
    assert settings.pdf_path == tmp_path / "a.pdf"


def test_missing_api_key_is_actionable(tmp_path):
    settings = Settings.load(tmp_path, environ={})
    assert settings.google_api_key is None
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY is not set"):
        settings.require_api_key()
    assert issubclass(ConfigError, RagError)


@pytest.mark.parametrize("env, message", [
    ({"EMBEDDING_PROVIDER": "openai"}, "EMBEDDING_PROVIDER must be"),
    ({"CHUNK_SIZE": "100", "CHUNK_OVERLAP": "100"}, "CHUNK_OVERLAP < CHUNK_SIZE"),
    ({"TOP_K": "0"}, "TOP_K must be at least 1"),
])
def test_validate_rejects_bad_settings(tmp_path, env, message):
    with pytest.raises(ConfigError, match=message):
        Settings.load(tmp_path, environ=env).validate()


def test_bool_and_min_score_parsing(tmp_path):
    settings = Settings.load(tmp_path, environ={"PDF_FONT_REPAIR": "true", "MIN_SCORE": "0.35"})
    assert settings.pdf_font_repair is True
    assert settings.min_score == pytest.approx(0.35)
    assert Settings.load(tmp_path, environ={}).pdf_font_repair is False


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


# --- project discovery ---------------------------------------------------------


def _project(tmp_path: Path, name: str = "project") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / PROJECT_MARKER).write_text("", encoding="utf-8")
    return folder


def test_marker_in_current_folder_or_above_is_found(tmp_path):
    project = _project(tmp_path)
    nested = project / "docs" / "deep"
    nested.mkdir(parents=True)

    assert find_project_dir(start=project, environ={}) == project.resolve()
    assert find_project_dir(start=nested, environ={}) == project.resolve()


def test_nearest_marker_wins(tmp_path):
    outer = _project(tmp_path, "outer")
    inner = outer / "inner"
    inner.mkdir()
    (inner / PROJECT_MARKER).write_text("", encoding="utf-8")
    assert find_project_dir(start=inner, environ={}) == inner.resolve()


def test_rag_project_dir_wins_over_marker_and_needs_no_marker(tmp_path):
    marked = _project(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    found = find_project_dir(start=marked, environ={"RAG_PROJECT_DIR": str(plain)})
    assert found == plain.resolve()


def test_missing_rag_project_dir_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="RAG_PROJECT_DIR does not exist"):
        find_project_dir(environ={"RAG_PROJECT_DIR": str(tmp_path / "nope")})


def test_no_marker_fails_clearly_and_creates_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ConfigError, match="No rag-kit project found.*--project.*RAG_PROJECT_DIR"):
        find_project_dir(start=empty, environ={})
    assert list(empty.iterdir()) == []


def test_load_without_project_dir_uses_discovery(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / ".env").write_text("QDRANT_PATH=store\n", encoding="utf-8")
    monkeypatch.chdir(project)

    settings = Settings.load(environ={})

    assert settings.project_dir == project.resolve()
    assert settings.qdrant_path == project.resolve() / "store"


def test_load_with_missing_explicit_project_dir_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        Settings.load(tmp_path / "missing", environ={})


def test_project_inside_the_package_is_refused():
    import rag_kit

    package_dir = Path(rag_kit.__file__).resolve().parent
    with pytest.raises(ConfigError, match="inside the installed rag-kit package"):
        Settings.load(package_dir, environ={})
    with pytest.raises(ConfigError, match="inside the installed rag-kit package"):
        find_project_dir(environ={"RAG_PROJECT_DIR": str(package_dir)})


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / ".git").exists(),
                    reason="only meaningful in the git checkout")
def test_this_checkout_is_a_project():
    from tests.conftest import ROOT

    assert find_project_dir(start=ROOT / "docs", environ={}) == ROOT
