"""All tunable settings in one place. Read from .env, with sane defaults."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- Step 1: PDF ---------------------------------------------------------
PDF_PATH = Path(os.getenv("PDF_PATH") or (BASE_DIR / "data" / "sample.pdf"))

# --- Step 4: Chunking ----------------------------------------------------
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# --- Step 5: Embedding ---------------------------------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
# None => detect the real dimension at runtime instead of hard-coding it.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM") or 0) or None
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "50"))

# --- Step 6: Qdrant ------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_PATH = os.getenv("QDRANT_PATH") or None  # local on-disk mode, no server
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pdf_rag")

# --- Step 9: Retrieval ---------------------------------------------------
TOP_K = int(os.getenv("TOP_K", "4"))

# --- Step 10: Gemini LLM -------------------------------------------------
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))


def require_api_key() -> None:
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and put your "
            "Gemini API key there (https://aistudio.google.com/app/apikey)."
        )
