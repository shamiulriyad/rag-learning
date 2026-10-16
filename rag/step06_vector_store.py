"""STEP 6 - Store in Qdrant.

Two ways to run Qdrant:
  server : docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
  local  : set QDRANT_PATH=qdrant_data in .env (no server needed; one process
           at a time)

Write side (`store_chunks`) creates the collection if needed. Read side
(`open_vector_store`) never creates anything: a missing store or collection, or
one built with a different embedding size, is an error with a fix in the message.

Re-indexing: every chunk gets a deterministic point ID built from its file name,
content hash and position. Ingesting a file again overwrites those points and
then deletes any older chunks of the same file name that were not overwritten,
so a document is *replaced*, never duplicated. `delete_document` removes one
document; `--recreate` drops the whole collection.
"""

import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models

from rag.errors import EmptyDocumentError, RagError, VectorStoreError
from rag.settings import Settings, default_settings
from rag.step05_embedding import detect_dimension

# Fixed namespace so the same chunk always maps to the same point ID.
_ID_NAMESPACE = uuid.UUID("8d2f1c3e-5b7a-4e0f-9c61-2a4b6d8e0f13")
_SOURCE_KEY = "metadata.source_file"


def describe_location(settings: Optional[Settings] = None) -> str:
    settings = settings or default_settings()
    if settings.qdrant_path:
        return f"local Qdrant store {settings.qdrant_path}"
    return f"Qdrant server {settings.qdrant_url}"


def get_client(create: bool = True, settings: Optional[Settings] = None) -> QdrantClient:
    """Open Qdrant. With create=False a missing local store is an error instead
    of being silently created empty."""
    settings = settings or default_settings()
    if settings.qdrant_path:
        path = Path(settings.qdrant_path)
        if not create and not path.exists():
            raise VectorStoreError(
                f"No local Qdrant store at {path}. Run `python cli.py ingest <file>` first, "
                f"or point QDRANT_PATH at the existing store (relative paths are resolved "
                f"from {settings.project_dir})."
            )
        try:
            return QdrantClient(path=str(path))
        except RuntimeError as exc:
            if "already accessed" in str(exc):
                raise VectorStoreError(
                    f"The local Qdrant store at {path} is in use by another process (the "
                    "API server, the Streamlit UI or another CLI command). Embedded Qdrant "
                    "allows one process at a time: stop the other one, or run a Qdrant "
                    "server and set QDRANT_URL instead of QDRANT_PATH."
                ) from exc
            raise VectorStoreError(f"Could not open {describe_location(settings)}: {exc}") from exc
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def collection_exists(client: QdrantClient, name: str,
                      settings: Optional[Settings] = None) -> bool:
    try:
        return client.collection_exists(name)
    except Exception as exc:
        raise VectorStoreError(
            f"Cannot reach {describe_location(settings)}: {exc}. Start the server "
            "(docker run -p 6333:6333 qdrant/qdrant) or set QDRANT_PATH for local mode."
        ) from exc


def collection_dimension(client: QdrantClient, name: str) -> int:
    vectors = client.get_collection(name).config.params.vectors
    if isinstance(vectors, dict):  # named vectors; LangChain uses the unnamed one
        vectors = vectors.get("") or next(iter(vectors.values()))
    return vectors.size


def check_dimension(client: QdrantClient, name: str, expected: int,
                    settings: Optional[Settings] = None) -> None:
    actual = collection_dimension(client, name)
    if actual != expected:
        raise VectorStoreError(
            f"Collection '{name}' holds {actual}-dimensional vectors, but "
            f"{(settings or default_settings()).embedding_model} produces {expected}. Vectors from different models "
            "are not comparable: set EMBEDDING_MODEL back to the model that built this "
            "collection, use another COLLECTION_NAME, or rebuild it with --recreate."
        )


def ensure_collection(client: QdrantClient, dimension: int, recreate: bool = False,
                      collection: Optional[str] = None,
                      settings: Optional[Settings] = None) -> None:
    settings = settings or default_settings()
    name = collection or settings.collection_name
    exists = collection_exists(client, name, settings)

    if exists and recreate:
        client.delete_collection(name)
        exists = False
        print(f"    dropped old collection '{name}'")

    if exists:
        check_dimension(client, name, dimension, settings)
        return

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )
    print(f"    created collection '{name}' (dim={dimension}, cosine)")


def get_vector_store(embeddings, client: QdrantClient = None,
                     collection: Optional[str] = None,
                     settings: Optional[Settings] = None) -> QdrantVectorStore:
    settings = settings or default_settings()
    return QdrantVectorStore(
        client=client or get_client(settings=settings),
        collection_name=collection or settings.collection_name,
        embedding=embeddings,
    )


def open_vector_store(embeddings, client: QdrantClient,
                      collection: Optional[str] = None,
                      settings: Optional[Settings] = None) -> QdrantVectorStore:
    """Read side: validate that the collection exists and matches the model."""
    settings = settings or default_settings()
    name = collection or settings.collection_name
    if not collection_exists(client, name, settings):
        found = [c.name for c in client.get_collections().collections]
        raise VectorStoreError(
            f"Collection '{name}' does not exist in {describe_location(settings)} "
            f"(found: {', '.join(found) or 'none'}). Ingest a document first, or fix "
            "COLLECTION_NAME."
        )
    check_dimension(client, name, detect_dimension(embeddings, settings), settings)
    return get_vector_store(embeddings, client, name, settings)


def chunk_point_id(metadata: dict) -> str:
    key = f"{metadata['source_file']}|{metadata.get('doc_id')}|{metadata['chunk_id']}"
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def _source_filter(source_file: str, keep_ids: Optional[List[str]] = None) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=_SOURCE_KEY, match=models.MatchValue(value=source_file))],
        must_not=[models.HasIdCondition(has_id=keep_ids)] if keep_ids else None,
    )


def store_chunks(chunks: List[Document], embeddings, recreate: bool = False,
                 client: QdrantClient = None, collection: Optional[str] = None,
                 settings: Optional[Settings] = None) -> dict:
    if not chunks:
        raise EmptyDocumentError("Nothing to store: the document produced no chunks.")

    settings = settings or default_settings()
    client = client or get_client(settings=settings)
    name = collection or settings.collection_name
    ensure_collection(client, detect_dimension(embeddings, settings), recreate=recreate,
                      collection=name, settings=settings)
    store = get_vector_store(embeddings, client, name, settings)
    ids = [chunk_point_id(c.metadata) for c in chunks]

    # Gemini caps a single embed call at 100 texts, so send in batches.
    # On the free tier it also caps ~100 texts/minute, so pause between batches.
    batch = settings.embed_batch_size
    for i, start in enumerate(range(0, len(chunks), batch)):
        if i > 0 and settings.embed_sleep:
            time.sleep(settings.embed_sleep)
        try:
            store.add_documents(chunks[start:start + batch], ids=ids[start:start + batch])
        except RagError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"Storing chunks failed after {start}/{len(chunks)}: {exc}. Running ingest "
                "again is safe - chunks are keyed by file and position, so nothing is "
                "duplicated."
            ) from exc
        print(f"    stored {min(start + batch, len(chunks))}/{len(chunks)} chunks", end="\r")

    # Replace, not append: drop older chunks of the same file that this run
    # did not overwrite (e.g. the file shrank or its content changed).
    replaced = 0
    for source in sorted({c.metadata["source_file"] for c in chunks}):
        source_ids = [pid for pid, c in zip(ids, chunks) if c.metadata["source_file"] == source]
        stale = _source_filter(source, keep_ids=source_ids)
        count = client.count(name, count_filter=stale, exact=True).count
        if count:
            client.delete(name, points_selector=models.FilterSelector(filter=stale))
            replaced += count

    total = client.count(name, exact=True).count
    note = f", {replaced} outdated chunks removed" if replaced else ""
    print(f"\n[6] Qdrant     : collection '{name}' now holds {total} vectors{note}")
    return {"collection": name, "stored": len(chunks), "removed_outdated": replaced,
            "total": total}


def delete_document(client: QdrantClient, source_file: str,
                    collection: Optional[str] = None,
                    settings: Optional[Settings] = None) -> int:
    """Remove every chunk of one file. Returns how many were deleted."""
    settings = settings or default_settings()
    name = collection or settings.collection_name
    if not collection_exists(client, name, settings):
        raise VectorStoreError(
            f"Collection '{name}' does not exist in {describe_location(settings)}.")
    selector = _source_filter(source_file)
    count = client.count(name, count_filter=selector, exact=True).count
    if count:
        client.delete(name, points_selector=models.FilterSelector(filter=selector))
    return count


def list_documents(client: QdrantClient, collection: Optional[str] = None,
                   settings: Optional[Settings] = None) -> Dict[str, int]:
    """File name -> number of chunks stored for it."""
    settings = settings or default_settings()
    name = collection or settings.collection_name
    if not collection_exists(client, name, settings):
        raise VectorStoreError(
            f"Collection '{name}' does not exist in {describe_location(settings)}.")
    counts: Dict[str, int] = {}
    offset = None
    while True:
        points, offset = client.scroll(name, limit=512, offset=offset,
                                       with_payload=True, with_vectors=False)
        for point in points:
            source = (point.payload or {}).get("metadata", {}).get("source_file", "(unknown)")
            counts[source] = counts.get(source, 0) + 1
        if offset is None:
            return dict(sorted(counts.items()))
