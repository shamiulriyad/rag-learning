"""STEP 6 - Store in Qdrant.

Two ways to run Qdrant:
  server : docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
  local  : set QDRANT_PATH=./qdrant_data in .env (no server needed)
"""

import time
from typing import List

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

import config


def get_client() -> QdrantClient:
    if config.QDRANT_PATH:
        return QdrantClient(path=config.QDRANT_PATH)
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)


def ensure_collection(client: QdrantClient, dimension: int, recreate: bool = False) -> None:
    name = config.COLLECTION_NAME
    exists = client.collection_exists(name)

    if exists and recreate:
        client.delete_collection(name)
        exists = False
        print(f"    dropped old collection '{name}'")

    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        print(f"    created collection '{name}' (dim={dimension}, cosine)")


def get_vector_store(embeddings, client: QdrantClient = None) -> QdrantVectorStore:
    return QdrantVectorStore(
        client=client or get_client(),
        collection_name=config.COLLECTION_NAME,
        embedding=embeddings,
    )


def store_chunks(chunks: List[Document], embeddings, recreate: bool = False) -> QdrantVectorStore:
    client = get_client()
    ensure_collection(client, detect_or_config_dim(embeddings), recreate=recreate)
    store = get_vector_store(embeddings, client)

    # Gemini caps a single embed call at 100 texts, so send in batches.
    # On the free tier it also caps ~100 texts/minute, so pause between batches.
    batch = config.EMBED_BATCH_SIZE
    for i, start in enumerate(range(0, len(chunks), batch)):
        window = chunks[start:start + batch]
        if i > 0 and config.EMBED_SLEEP:
            time.sleep(config.EMBED_SLEEP)
        store.add_documents(window)
        print(f"    stored {min(start + batch, len(chunks))}/{len(chunks)} chunks", end="\r")

    count = client.count(config.COLLECTION_NAME, exact=True).count
    print(f"\n[6] Qdrant     : collection '{config.COLLECTION_NAME}' now holds {count} vectors")
    return store


def detect_or_config_dim(embeddings) -> int:
    from rag.step05_embedding import detect_dimension
    return detect_dimension(embeddings)
