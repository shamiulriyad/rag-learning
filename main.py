"""STEP 7-11 over HTTP - the RAG service the .NET backend talks to.

    uvicorn main:app --port 8000          # run from this folder

`backend/Services/RagService.cs` calls exactly two endpoints:

    GET  /health                     -> {"status": "ok"}
    POST /query  {question, top_k?}  -> {"answer": str,
                                         "sources": [{page, source, score}]}

Qdrant runs embedded (QDRANT_PATH in .env), which allows only one process at a
time - run `python ingest.py` first, then start this with a single worker.
"""

import re
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from rag.step05_embedding import get_embeddings
from rag.step06_vector_store import get_vector_store
from rag.step08_query_embedding import embed_question
from rag.step09_retrieve import retrieve
from rag.step10_generate import generate_answer, get_llm

# The embedding model, Qdrant client and LLM are built once and reused for every
# request. Kept in a dict so the lifespan handler and the lazy fallback share it.
_state: dict = {}


def _ensure_ready() -> None:
    """Load models / open Qdrant on first use. Safe to call repeatedly."""
    if _state.get("ready"):
        return
    embeddings = get_embeddings()                       # step 5 (read side)
    _state["embeddings"] = embeddings
    _state["vector_store"] = get_vector_store(embeddings)  # step 6 (read side)
    _state["llm"] = get_llm()                           # step 10
    _state["ready"] = True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm up at startup so the first real request is fast. If it fails (e.g. the
    # collection has not been ingested yet) the service still starts and /health
    # stays green; /query then returns a clear 503.
    try:
        _ensure_ready()
    except Exception as exc:  # noqa: BLE001 - reported back on /query
        print(f"[startup] not ready yet: {exc}")
    yield
    _state.clear()


app = FastAPI(title="PDF RAG service", lifespan=lifespan)


class QueryIn(BaseModel):
    question: str
    top_k: Optional[int] = None


class SourceOut(BaseModel):
    page: Optional[int] = None
    source: str
    score: float


class AnswerOut(BaseModel):
    answer: str
    sources: List[SourceOut]


# Gemini tags claims with [S1], [S2]... (sometimes back-to-back) - strip them.
_MARKER_RE = re.compile(r"[ \t]*(?:\[S\d+\])+")


def strip_markers(text: str) -> str:
    return _MARKER_RE.sub("", text).strip()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ready": bool(_state.get("ready"))}


@app.post("/query", response_model=AnswerOut)
def query(body: QueryIn) -> AnswerOut:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    try:
        _ensure_ready()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"RAG service not ready: {exc}. Run `python ingest.py` first.",
        ) from exc

    k = body.top_k or config.TOP_K
    query_vector = embed_question(_state["embeddings"], question)          # 8
    scored_docs = retrieve(_state["vector_store"], query_vector, k)        # 9
    answer = generate_answer(question, scored_docs, llm=_state["llm"])     # 10
    answer = strip_markers(answer)

    sources = [                                                           # 11
        SourceOut(
            page=doc.metadata.get("page_number"),
            source=doc.metadata.get("source_file", "document"),
            score=float(score),
        )
        for doc, score in scored_docs
    ]
    return AnswerOut(answer=answer, sources=sources)
