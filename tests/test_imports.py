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
    with pytest.raises(GenerationError, match="pip install langchain-google-genai"):
        get_llm(settings)
