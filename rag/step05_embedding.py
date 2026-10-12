"""STEP 5 - Embedding.

One embedding object is shared by ingestion (step 6) and querying (step 8) -
the same model must be used on both sides or the vectors are not comparable.

Two providers, chosen by EMBEDDING_PROVIDER in .env:
  huggingface : a local sentence-transformers model, no API key, no quota
  google      : Gemini embeddings (needs an API key with embedding quota)
"""

import config
from rag.errors import EmbeddingProviderError


def get_embeddings():
    config.validate()
    if config.EMBEDDING_PROVIDER == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise EmbeddingProviderError(
                "EMBEDDING_PROVIDER=huggingface needs `pip install langchain-huggingface "
                f"sentence-transformers` ({exc})."
            ) from exc
        try:
            embeddings = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Could not load embedding model {config.EMBEDDING_MODEL!r}: {exc}. "
                "Check the model name and your network (the first run downloads it "
                "into the Hugging Face cache)."
            ) from exc
        print(f"[5] Embedding  : {config.EMBEDDING_MODEL} (local)")
        return embeddings

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError as exc:
        raise EmbeddingProviderError(
            f"EMBEDDING_PROVIDER=google needs `pip install langchain-google-genai` ({exc})."
        ) from exc

    embeddings = GoogleGenerativeAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
    )
    print(f"[5] Embedding  : {config.EMBEDDING_MODEL}")
    return embeddings


def detect_dimension(embeddings) -> int:
    """Ask the model for one vector and measure it.

    Safer than hard-coding a size: it changes with the model (384 for
    all-MiniLM-L6-v2, 3072 for gemini-embedding-001), and a mismatch only
    shows up later as a Qdrant dimension error.
    """
    if config.EMBEDDING_DIM:
        return config.EMBEDDING_DIM

    try:
        dim = len(embeddings.embed_query("dimension probe"))
    except Exception as exc:
        raise EmbeddingProviderError(
            f"Embedding model {config.EMBEDDING_MODEL!r} failed on a test input: {exc}"
        ) from exc
    print(f"    vector size: {dim}")
    return dim
