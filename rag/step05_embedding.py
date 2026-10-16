"""STEP 5 - Embedding.

One embedding object is shared by ingestion (step 6) and querying (step 8) -
the same model must be used on both sides or the vectors are not comparable.

Two providers, chosen by EMBEDDING_PROVIDER in .env:
  huggingface : a local sentence-transformers model, no API key, no quota
  google      : Gemini embeddings (needs an API key with embedding quota)
"""

from typing import Optional

from rag.errors import EmbeddingProviderError
from rag.settings import Settings, default_settings


def get_embeddings(settings: Optional[Settings] = None):
    settings = settings or default_settings()
    settings.validate()
    if settings.embedding_provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise EmbeddingProviderError(
                "EMBEDDING_PROVIDER=huggingface needs `pip install langchain-huggingface "
                f"sentence-transformers` ({exc})."
            ) from exc
        try:
            embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Could not load embedding model {settings.embedding_model!r}: {exc}. "
                "Check the model name and your network (the first run downloads it "
                "into the Hugging Face cache)."
            ) from exc
        print(f"[5] Embedding  : {settings.embedding_model} (local)")
        return embeddings

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError as exc:
        raise EmbeddingProviderError(
            f"EMBEDDING_PROVIDER=google needs `pip install langchain-google-genai` ({exc})."
        ) from exc

    embeddings = GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )
    print(f"[5] Embedding  : {settings.embedding_model}")
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
    print(f"    vector size: {dim}")
    return dim
