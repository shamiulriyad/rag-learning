"""Settings for this checkout, as module-level names (kept for compatibility).

New code should use `rag.settings.Settings` and pass it in explicitly; this
module builds one from the .env next to this file and registers it as the
default for the pipeline.

The .env file is always the one next to this file (override with RAG_ENV_FILE),
and relative paths in it are resolved against this directory - never against
the current working directory - so running a command from somewhere else
cannot silently point at a different, empty Qdrant store.

Importing this module no longer copies .env into os.environ. The CLI, the API
service and the UI do that explicitly, for an allow-list of keys only (see
rag/env.py).
"""

import os
from pathlib import Path

from rag.errors import ConfigError  # noqa: F401 - re-exported
from rag.settings import SUPPORTED_EXTENSIONS, Settings, set_default_settings  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = Path(os.getenv("RAG_ENV_FILE") or (BASE_DIR / ".env"))

SETTINGS = Settings.load(BASE_DIR, env_file=ENV_FILE)
set_default_settings(SETTINGS)

PDF_PATH = SETTINGS.pdf_path
PDF_FONT_REPAIR = SETTINGS.pdf_font_repair
CHUNK_SIZE = SETTINGS.chunk_size
CHUNK_OVERLAP = SETTINGS.chunk_overlap
GOOGLE_API_KEY = SETTINGS.google_api_key
EMBEDDING_PROVIDER = SETTINGS.embedding_provider
EMBEDDING_MODEL = SETTINGS.embedding_model
EMBEDDING_DIM = SETTINGS.embedding_dim
EMBED_BATCH_SIZE = SETTINGS.embed_batch_size
EMBED_SLEEP = SETTINGS.embed_sleep
QDRANT_URL = SETTINGS.qdrant_url
QDRANT_API_KEY = SETTINGS.qdrant_api_key
QDRANT_PATH = SETTINGS.qdrant_path
COLLECTION_NAME = SETTINGS.collection_name
TOP_K = SETTINGS.top_k
MIN_SCORE = SETTINGS.min_score
LLM_MODEL = SETTINGS.llm_model
TEMPERATURE = SETTINGS.temperature


def resolve_path(value) -> Path:
    """Absolute paths stay as they are; relative ones are taken from BASE_DIR."""
    return SETTINGS.resolve_path(value)


def require_api_key() -> None:
    SETTINGS.require_api_key()


def validate() -> None:
    """Fail early on settings that would only break halfway through a run."""
    SETTINGS.validate()
