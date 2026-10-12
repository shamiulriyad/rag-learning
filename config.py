"""All tunable settings in one place. Read from .env, with sane defaults.

The .env file is always the one next to this file (override with RAG_ENV_FILE),
and relative paths in it are resolved against this directory - never against
the current working directory - so running a command from somewhere else
cannot silently point at a different, empty Qdrant store.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from rag.errors import RagError

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = Path(os.getenv("RAG_ENV_FILE") or (BASE_DIR / ".env"))
load_dotenv(ENV_FILE)


class ConfigError(RagError):
    """A setting is missing or invalid. The message says how to fix it."""


def resolve_path(value) -> Path:
    """Absolute paths stay as they are; relative ones are taken from BASE_DIR."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _int(name: str, default: str) -> int:
    raw = os.getenv(name) or default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None


def _float(name: str, default: str) -> float:
    raw = os.getenv(name) or default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None


def _bool(name: str, default: str) -> bool:
    return (os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


# --- Step 1: Input document ------------------------------------------------
# Default file for `ingest` when no path is given on the command line.
PDF_PATH = resolve_path(os.getenv("PDF_PATH") or "data/sample.pdf")
SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md")

# --- Step 2: Extraction ----------------------------------------------------
# Repairs PDFs whose subset fonts have no ToUnicode map (see
# rag/pdf_font_repair.py). Off by default: ordinary PDFs do not need it.
PDF_FONT_REPAIR = _bool("PDF_FONT_REPAIR", "false")

# --- Step 4: Chunking ------------------------------------------------------
CHUNK_SIZE = _int("CHUNK_SIZE", "1000")
CHUNK_OVERLAP = _int("CHUNK_OVERLAP", "150")

# --- Step 5: Embedding -----------------------------------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or None
# "huggingface" runs a local model - no API key, no quota, no cost.
# "google" uses Gemini embeddings (needs a real API key with embedding quota).
EMBEDDING_PROVIDER = (os.getenv("EMBEDDING_PROVIDER") or "huggingface").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or (
    "BAAI/bge-m3" if EMBEDDING_PROVIDER == "huggingface" else "models/gemini-embedding-001"
)
# None => detect the real dimension at runtime instead of hard-coding it.
EMBEDDING_DIM = _int("EMBEDDING_DIM", "0") or None
EMBED_BATCH_SIZE = _int("EMBED_BATCH_SIZE", "90")
# Gemini free tier allows ~100 embedded texts / minute; pause between batches so
# a large PDF does not trip a 429. Not needed for a local model.
EMBED_SLEEP = _float("EMBED_SLEEP", "60" if EMBEDDING_PROVIDER == "google" else "0")

# --- Step 6: Qdrant --------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL") or "http://localhost:6333"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
# Local on-disk mode, no server. Takes priority over QDRANT_URL when set.
QDRANT_PATH = resolve_path(os.getenv("QDRANT_PATH")) if os.getenv("QDRANT_PATH") else None
COLLECTION_NAME = os.getenv("COLLECTION_NAME") or "pdf_rag"

# --- Step 9: Retrieval -----------------------------------------------------
TOP_K = _int("TOP_K", "4")
# Chunks scoring below this are treated as "not relevant". Unset keeps every hit.
MIN_SCORE = _float("MIN_SCORE", "0") if os.getenv("MIN_SCORE") else None

# --- Step 10: Gemini LLM ---------------------------------------------------
LLM_MODEL = os.getenv("LLM_MODEL") or "gemini-2.5-flash"
TEMPERATURE = _float("TEMPERATURE", "0.2")


def require_api_key() -> None:
    if not GOOGLE_API_KEY:
        raise ConfigError(
            f"GOOGLE_API_KEY is not set. Copy .env.example to {ENV_FILE} and put your "
            "Gemini API key there (https://aistudio.google.com/app/apikey)."
        )


def validate() -> None:
    """Fail early on settings that would only break halfway through a run."""
    if EMBEDDING_PROVIDER not in {"huggingface", "google"}:
        raise ConfigError(
            f"EMBEDDING_PROVIDER must be 'huggingface' or 'google', got {EMBEDDING_PROVIDER!r}."
        )
    if CHUNK_SIZE <= 0 or not 0 <= CHUNK_OVERLAP < CHUNK_SIZE:
        raise ConfigError(
            f"Need CHUNK_SIZE > 0 and 0 <= CHUNK_OVERLAP < CHUNK_SIZE "
            f"(got {CHUNK_SIZE} / {CHUNK_OVERLAP})."
        )
    if TOP_K <= 0:
        raise ConfigError(f"TOP_K must be at least 1, got {TOP_K}.")
    if EMBEDDING_PROVIDER == "google":
        require_api_key()
