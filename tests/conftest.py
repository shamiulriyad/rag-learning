"""Unit tests never read the real .env, never touch the real Qdrant store and
never call an external API. Shared fakes live here."""

import os
from pathlib import Path

import pytest

from rag_kit.settings import SETTING_NAMES, Settings, set_default_settings

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ENV = Path(__file__).parent / "fixtures" / "empty_env.txt"

# Cleared so a developer's shell cannot leak into tests.
for _name in (*SETTING_NAMES, "RAG_PROJECT_DIR", "RAG_EXPORT_ENV"):
    os.environ.pop(_name, None)
os.environ["RAG_ENV_FILE"] = str(EMPTY_ENV)  # never the real .env, here or in subprocesses
os.environ["RAG_API_WARMUP"] = "0"

# The folder above tests/ is the project for code that is not given settings
# (the checkout has a rag-kit.toml; so does a copied test tree, see README).
TEST_SETTINGS = Settings.load(ROOT)
set_default_settings(TEST_SETTINGS)


@pytest.fixture
def test_settings() -> Settings:
    return TEST_SETTINGS


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
