"""Step 6 against an in-memory Qdrant with fake embeddings - no disk, no network."""

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from rag_kit.errors import EmptyDocumentError, VectorStoreError
from rag_kit.step06_vector_store import (delete_document, get_client, list_documents,
                                     open_vector_store, store_chunks)

COLLECTION = "unit_test"


def _chunks(source, doc_id, count):
    return [Document(page_content=f"{source} chunk {i} about nouns",
                     metadata={"source_file": source, "doc_id": doc_id, "chunk_id": i,
                               "page_number": 1})
            for i in range(count)]


def _store(chunks, embeddings, client, **kw):
    return store_chunks(chunks, embeddings, client=client, collection=COLLECTION, **kw)


def test_store_creates_collection_and_counts(fake_embeddings, memory_client):
    report = _store(_chunks("a.pdf", "v1", 5), fake_embeddings, memory_client)
    assert report == {"collection": COLLECTION, "stored": 5, "removed_outdated": 0, "total": 5}


def test_reingesting_same_file_does_not_duplicate(fake_embeddings, memory_client):
    _store(_chunks("a.pdf", "v1", 5), fake_embeddings, memory_client)
    report = _store(_chunks("a.pdf", "v1", 5), fake_embeddings, memory_client)
    assert report["total"] == 5 and report["removed_outdated"] == 0


def test_changed_file_replaces_old_chunks_only(fake_embeddings, memory_client):
    _store(_chunks("a.pdf", "v1", 5), fake_embeddings, memory_client)
    _store(_chunks("b.md", "x", 2), fake_embeddings, memory_client)
    report = _store(_chunks("a.pdf", "v2", 3), fake_embeddings, memory_client)

    assert report["removed_outdated"] == 5
    assert list_documents(memory_client, COLLECTION) == {"a.pdf": 3, "b.md": 2}


def test_delete_document(fake_embeddings, memory_client):
    _store(_chunks("a.pdf", "v1", 4) + _chunks("b.md", "x", 2), fake_embeddings, memory_client)
    assert delete_document(memory_client, "a.pdf", COLLECTION) == 4
    assert delete_document(memory_client, "a.pdf", COLLECTION) == 0
    assert list_documents(memory_client, COLLECTION) == {"b.md": 2}


def test_dimension_mismatch_fails_instead_of_overwriting(fake_embeddings, memory_client):
    _store(_chunks("a.pdf", "v1", 2), fake_embeddings, memory_client)
    other_model = DeterministicFakeEmbedding(size=8)

    with pytest.raises(VectorStoreError, match="holds 16-dimensional vectors"):
        _store(_chunks("c.pdf", "z", 2), other_model, memory_client)
    with pytest.raises(VectorStoreError, match="holds 16-dimensional vectors"):
        open_vector_store(other_model, memory_client, COLLECTION)
    assert memory_client.count(COLLECTION).count == 2


def test_recreate_drops_everything(fake_embeddings, memory_client):
    _store(_chunks("a.pdf", "v1", 4), fake_embeddings, memory_client)
    report = _store(_chunks("b.md", "x", 1), fake_embeddings, memory_client, recreate=True)
    assert report["total"] == 1


def test_read_side_never_creates_a_collection(fake_embeddings, memory_client):
    with pytest.raises(VectorStoreError, match="does not exist"):
        open_vector_store(fake_embeddings, memory_client, "nope")
    assert not memory_client.collection_exists("nope")


def test_storing_nothing_is_an_error(fake_embeddings, memory_client):
    with pytest.raises(EmptyDocumentError):
        _store([], fake_embeddings, memory_client)


def test_missing_local_store_is_not_created_on_read(tmp_path, test_settings):
    missing = tmp_path / "qdrant_data"
    settings = test_settings.replace(qdrant_path=missing)
    with pytest.raises(VectorStoreError, match="No local Qdrant store"):
        get_client(create=False, settings=settings)
    assert not missing.exists()


def test_locked_local_store_has_actionable_error(tmp_path, test_settings):
    settings = test_settings.replace(qdrant_path=tmp_path / "store")
    first = get_client(create=True, settings=settings)
    try:
        with pytest.raises(VectorStoreError, match="in use by another process"):
            get_client(create=False, settings=settings)
    finally:
        first.close()
