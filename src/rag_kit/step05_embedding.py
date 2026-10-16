"""STEP 5 - Embedding.

One embedding object is shared by ingestion (step 6) and querying (step 8) -
the same model must be used on both sides or the vectors are not comparable.

Two providers, chosen by EMBEDDING_PROVIDER in .env:
  huggingface : a local sentence-transformers model, no API key, no quota
  google      : Gemini embeddings (needs an API key with embedding quota)
"""

import logging
from typing import Optional

from rag_kit.errors import EmbeddingProviderError
from rag_kit.settings import Settings, default_settings

logger = logging.getLogger(__name__)

LOCAL_EXTRA_HINT = ('EMBEDDING_PROVIDER=huggingface needs the local extra: '
                    'pip install "rag-kit[local]"')
GEMINI_EXTRA_HINT = ('EMBEDDING_PROVIDER=google needs the gemini extra: '
                     'pip install "rag-kit[gemini]"')


def get_embeddings(settings: Optional[Settings] = None):
    settings = settings or default_settings()
    settings.validate()
    if settings.embedding_provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise EmbeddingProviderError(f"{LOCAL_EXTRA_HINT} ({exc}).") from exc
        try:
            embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
        except ImportError as exc:  # sentence-transformers is imported only here
            raise EmbeddingProviderError(f"{LOCAL_EXTRA_HINT} ({exc}).") from exc
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Could not load embedding model {settings.embedding_model!r}: {exc}. "
                "Check the model name and your network (the first run downloads it "
                "into the Hugging Face cache)."
            ) from exc
        logger.info(f"[5] Embedding  : {settings.embedding_model} (local)")
        return embeddings

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError as exc:
        raise EmbeddingProviderError(f"{GEMINI_EXTRA_HINT} ({exc}).") from exc

    embeddings = GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )
    logger.info(f"[5] Embedding  : {settings.embedding_model}")
    return embeddings


def detect_dimension(embeddings, settings: Optional[Settings] = None) -> int:
    """Ask the model for one vector and measure it.

    Safer than hard-coding a size: it changes with the model (384 for
    all-MiniLM-L6-v2, 3072 for gemini-embedding-001), and a mismatch only
    shows up later as a Qdrant dimension error.
    """
    settings = settings or default_settings()
    if settings.embedding_dim:
        return settings.embedding_dim

    try:
        dim = len(embeddings.embed_query("dimension probe"))
    except Exception as exc:
        raise EmbeddingProviderError(
            f"Embedding model {settings.embedding_model!r} failed on a test input: {exc}"
        ) from exc
    logger.info(f"    vector size: {dim}")
    return dim
