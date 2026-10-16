"""Optional providers are imported only when they are used."""

import os
import subprocess
import sys

from tests.conftest import EMPTY_ENV, ROOT


def _loaded_after(statement: str, module: str) -> bool:
    code = f"import sys; {statement}; print({module!r} in sys.modules)"
    env = {**os.environ, "RAG_ENV_FILE": str(EMPTY_ENV)}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "True"


def test_pipeline_import_does_not_load_gemini():
    assert not _loaded_after("import rag_kit.pipeline", "langchain_google_genai")


def test_cli_import_does_not_load_gemini():
    assert not _loaded_after("import rag_kit.cli", "langchain_google_genai")


def test_get_llm_without_gemini_sdk_is_actionable(test_settings, monkeypatch):
    import pytest

    from rag_kit.errors import GenerationError
    from rag_kit.step10_generate import get_llm

    settings = test_settings.replace(google_api_key="test-key-not-real")
    monkeypatch.setitem(sys.modules, "langchain_google_genai", None)  # import now fails
    with pytest.raises(GenerationError, match=r"gemini extra: pip install \"rag-kit\[gemini\]\""):
        get_llm(settings)


def _without(monkeypatch, module):
    monkeypatch.setitem(sys.modules, module, None)  # importing it now raises ImportError


def test_missing_local_extra_names_the_extra(test_settings, monkeypatch):
    import pytest

    from rag_kit.errors import EmbeddingProviderError
    from rag_kit.step05_embedding import get_embeddings

    _without(monkeypatch, "langchain_huggingface")
    hint = r'local extra: pip install "rag-kit\[local\]"'
    with pytest.raises(EmbeddingProviderError, match=hint):
        get_embeddings(test_settings.replace(embedding_provider="huggingface"))


def test_missing_sentence_transformers_names_the_local_extra(test_settings, monkeypatch):
    import types

    import pytest

    from rag_kit.errors import EmbeddingProviderError
    from rag_kit.step05_embedding import get_embeddings

    class HuggingFaceEmbeddings:  # like langchain-huggingface without sentence-transformers
        def __init__(self, **kwargs):
            raise ImportError("No module named 'sentence_transformers'")

    fake = types.ModuleType("langchain_huggingface")
    fake.HuggingFaceEmbeddings = HuggingFaceEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_huggingface", fake)
    with pytest.raises(EmbeddingProviderError, match=r'rag-kit\[local\].*sentence_transformers'):
        get_embeddings(test_settings.replace(embedding_provider="huggingface"))


def test_missing_gemini_extra_for_embeddings_names_the_extra(test_settings, monkeypatch):
    import pytest

    from rag_kit.errors import EmbeddingProviderError
    from rag_kit.step05_embedding import get_embeddings

    _without(monkeypatch, "langchain_google_genai")
    settings = test_settings.replace(embedding_provider="google", google_api_key="not-real")
    hint = r'gemini extra: pip install "rag-kit\[gemini\]"'
    with pytest.raises(EmbeddingProviderError, match=hint):
        get_embeddings(settings)
