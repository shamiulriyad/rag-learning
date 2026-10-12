"""Optional HTTP API over the pipeline (steps 7-11).

    pip install -r requirements-api.txt
    python cli.py serve                    # or: uvicorn main:app --port 8000

    GET  /health                     -> {"status": "ok", "ready": bool}
    POST /query  {question, top_k?}  -> {"answer": str, "status": str,
                                         "sources": [{page, source, score, marker, ...}]}

`answer` has the [S1] markers stripped; each source carries its `marker` so a
client can still map claims to chunks. `status` is "answered" or "no_results".

Qdrant in local mode allows only one process at a time - run ingestion first,
then start this with a single worker.
"""

import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from rag.errors import RagError
from rag.pipeline import Pipeline
from rag.step11_answer import strip_markers  # noqa: F401 - re-exported for callers

_pipeline: Optional[Pipeline] = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm up at startup so the first real request is fast. If it fails (e.g. the
    # collection has not been ingested yet) the service still starts and /health
    # stays green; /query then returns a clear 503.
    if os.getenv("RAG_API_WARMUP", "1") == "1":
        try:
            get_pipeline().warm_up()
        except Exception as exc:  # noqa: BLE001 - reported back on /query
            print(f"[startup] not ready yet: {exc}")
    yield
    if _pipeline is not None:
        _pipeline.close()


app = FastAPI(title="RAG toolkit service", lifespan=lifespan)


class QueryIn(BaseModel):
    question: str
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class SourceOut(BaseModel):
    page: Optional[int] = None
    source: str
    score: float
    marker: str
    chunk_id: Optional[int] = None
    text: str


class AnswerOut(BaseModel):
    answer: str
    status: str
    sources: List[SourceOut]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ready": _pipeline is not None and _pipeline.ready}


@app.post("/query", response_model=AnswerOut)
def query(body: QueryIn, pipeline: Pipeline = Depends(get_pipeline)) -> AnswerOut:
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    try:
        result = pipeline.ask(body.question, k=body.top_k)
    except RagError as exc:
        raise HTTPException(status_code=503, detail=f"RAG service not ready: {exc}") from exc

    return AnswerOut(
        answer=result.answer_without_markers,
        status=result.status,
        sources=[
            SourceOut(page=s["page"], source=s["file"] or "document", score=s["score"],
                      marker=s["marker"], chunk_id=s["chunk_id"], text=s["text"])
            for s in result.sources
        ],
    )
