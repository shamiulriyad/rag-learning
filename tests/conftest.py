"""Unit tests never read the real .env, never touch the real Qdrant store and
never call an external API. Shared fakes live here."""

import importlib
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ENV = Path(__file__).parent / "fixtures" / "empty_env.txt"

# Settings config.py reads. Cleared so a developer's shell cannot leak into tests.
CONFIG_VARS = (
    "GOOGLE_API_KEY", "PDF_PATH", "PDF_FONT_REPAIR", "CHUNK_SIZE", "CHUNK_OVERLAP",
    "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIM", "EMBED_BATCH_SIZE",
    "EMBED_SLEEP", "QDRANT_URL", "QDRANT_API_KEY", "QDRANT_PATH", "COLLECTION_NAME",
    "TOP_K", "MIN_SCORE", "LLM_MODEL", "TEMPERATURE",
)
for _name in CONFIG_VARS:
    os.environ.pop(_name, None)
os.environ["RAG_ENV_FILE"] = str(EMPTY_ENV)  # must happen before `import config`
os.environ["RAG_API_WARMUP"] = "0"

import config  # noqa: E402


@pytest.fixture
def load_config(monkeypatch):
    """Reload config.py with extra environment variables; restored afterwards."""
    def _load(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _load
    monkeypatch.undo()
    importlib.reload(config)


@pytest.fixture
def fake_embeddings():
    from langchain_core.embeddings import DeterministicFakeEmbedding
    return DeterministicFakeEmbedding(size=16)


@pytest.fixture
def memory_client():
    from qdrant_client import QdrantClient
    client = QdrantClient(":memory:")
    yield client
    client.close()


class FailingLLM:
    """Stands in for the LLM where a test must prove it is never called, or that
    a provider failure is reported cleanly."""

    def __init__(self, message="LLM must not be called"):
        self.message = message

    def __call__(self, _prompt):
        raise RuntimeError(self.message)


@pytest.fixture
def fake_llm():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    return FakeListChatModel(responses=["Nouns name things [S1]. They can be plural [S2]."])


@pytest.fixture
def failing_llm():
    from langchain_core.runnables import RunnableLambda
    return RunnableLambda(FailingLLM())


def make_text_file(tmp_path: Path, name: str, paragraphs: int, topic: str = "noun") -> Path:
    body = "\n\n".join(
        f"Paragraph {i} explains the {topic}. A {topic} is described here in detail, "
        f"with examples that make the idea of the {topic} clear to every reader."
        for i in range(paragraphs)
    )
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path
