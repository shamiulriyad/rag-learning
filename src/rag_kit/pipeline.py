"""The 11 steps wired together, shared by the CLI, FastAPI and Streamlit.

    pipeline = Pipeline()                      # nothing is loaded yet
    pipeline.ingest("data/book.pdf")           # steps 1-6
    result = pipeline.ask("What is a noun?")   # steps 7-11 (minus printing)
    pipeline.close()

The embedding model, Qdrant client and LLM are created on first use and then
reused. A local Qdrant store allows one client per process, so keep one
Pipeline per process.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.documents import Document

from rag_kit.errors import EmptyDocumentError
from rag_kit.settings import Settings, default_settings
from rag_kit.step01_load_pdf import load_document
from rag_kit.step02_extract_text import extract_text
from rag_kit.step03_clean_text import clean_documents
from rag_kit.step04_chunking import chunk_documents
from rag_kit.step05_embedding import get_embeddings
from rag_kit.step06_vector_store import (delete_document, get_client, list_documents,
                                     open_vector_store, store_chunks)
from rag_kit.step08_query_embedding import embed_question
from rag_kit.step09_retrieve import retrieve
from rag_kit.step10_generate import NO_RESULTS_ANSWER, generate_answer, get_llm
from rag_kit.step11_answer import build_sources, strip_markers

ScoredDocs = List[Tuple[Document, float]]


@dataclass
class AnswerResult:
    question: str
    answer: str                      # raw model output, with [S1] markers
    status: str                      # "answered" or "no_results"
    sources: List[dict] = field(default_factory=list)
    scored_docs: ScoredDocs = field(default_factory=list, repr=False)

    @property
    def answer_without_markers(self) -> str:
        return strip_markers(self.answer)


class Pipeline:
    def __init__(self, collection: Optional[str] = None, embeddings=None, client=None, llm=None,
                 settings: Optional[Settings] = None):
        self.settings = settings or default_settings()
        self.collection = collection or self.settings.collection_name
        self._embeddings = embeddings
        self._client = client
        self._llm = llm
        self._vector_store = None
        self._lock = threading.RLock()

    # --- lazily created resources -------------------------------------------
    @property
    def embeddings(self):
        with self._lock:
            if self._embeddings is None:
                self._embeddings = get_embeddings(self.settings)          # 5
            return self._embeddings

    def client(self, create: bool = False):
        with self._lock:
            if self._client is None:
                self._client = get_client(create=create, settings=self.settings)
            return self._client

    @property
    def vector_store(self):
        with self._lock:
            if self._vector_store is None:                                 # 6 (read side)
                self._vector_store = open_vector_store(self.embeddings, self.client(),
                                                       self.collection, self.settings)
            return self._vector_store

    @property
    def llm(self):
        with self._lock:
            if self._llm is None:
                self._llm = get_llm(self.settings)                         # 10
            return self._llm

    @property
    def ready(self) -> bool:
        """True once the collection has been opened and validated."""
        return self._vector_store is not None

    def warm_up(self, llm: bool = True) -> None:
        """Load everything a query needs, so the first request is not slow."""
        _ = self.vector_store
        if llm:
            _ = self.llm

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
            self._client = self._vector_store = None

    # --- steps 1-6 -----------------------------------------------------------
    def ingest(self, path, recreate: bool = False, font_repair: Optional[bool] = None) -> dict:
        source = load_document(path)                                       # 1
        pages = extract_text(source, font_repair=font_repair,              # 2
                             settings=self.settings)
        pages = clean_documents(pages)                                     # 3
        if not pages:
            raise EmptyDocumentError(
                f"No usable text in {source.name} after cleaning. If it is a scanned "
                "PDF, run OCR first (e.g. `ocrmypdf in.pdf out.pdf`)."
            )
        chunks = chunk_documents(pages, self.settings.chunk_size,             # 4
                                 self.settings.chunk_overlap)
        with self._lock:
            report = store_chunks(chunks, self.embeddings, recreate=recreate,     # 5 + 6
                                  client=self.client(create=True), collection=self.collection,
                                  settings=self.settings)
            self._vector_store = None  # re-validate on next read (collection may be new)
        report["file"] = source.name
        report["pages"] = len(pages)
        return report

    # --- steps 8-11 ----------------------------------------------------------
    def search(self, question: str, k: Optional[int] = None,
               min_score: Optional[float] = None) -> ScoredDocs:
        question = _require_question(question)
        query_vector = embed_question(self.embeddings, question)           # 8
        return retrieve(self.vector_store, query_vector, k or self.settings.top_k,  # 9
                        self.settings.min_score if min_score is None else min_score)

    def ask(self, question: str, k: Optional[int] = None,
            min_score: Optional[float] = None) -> AnswerResult:
        question = _require_question(question)
        scored_docs = self.search(question, k=k, min_score=min_score)
        if not scored_docs:
            return AnswerResult(question, NO_RESULTS_ANSWER, "no_results")
        answer = generate_answer(question, scored_docs, llm=self.llm,     # 10
                                 settings=self.settings)
        return AnswerResult(question, answer, "answered",                  # 11
                            build_sources(scored_docs), scored_docs)

    # --- maintenance ---------------------------------------------------------
    def documents(self) -> dict:
        return list_documents(self.client(), self.collection, self.settings)

    def delete(self, source_file: str) -> int:
        with self._lock:
            removed = delete_document(self.client(), Path(source_file).name, self.collection,
                                      self.settings)
            self._vector_store = None
            return removed


def _require_question(question: str) -> str:
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is empty.")
    return question
