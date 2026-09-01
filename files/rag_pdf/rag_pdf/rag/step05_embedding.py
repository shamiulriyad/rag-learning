"""STEP 5 - Embedding.

One embedding object is shared by ingestion (step 6) and querying (step 8) -
the same model must be used on both sides or the vectors are not comparable.

Two providers, chosen by EMBEDDING_PROVIDER in .env:
  huggingface : a local sentence-transformers model, no API key, no quota
  google      : Gemini embeddings (needs an API key with embedding quota)
"""

import config


def get_embeddings():
    if config.EMBEDDING_PROVIDER == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)
        print(f"[5] Embedding  : {config.EMBEDDING_MODEL} (local)")
        return embeddings

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    config.require_api_key()
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

    dim = len(embeddings.embed_query("dimension probe"))
    print(f"    vector size: {dim}")
    return dim
