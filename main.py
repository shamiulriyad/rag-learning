"""Optional HTTP API over the pipeline (steps 7-11).

    pip install -r requirements-api.txt
    python cli.py serve                    # or: uvicorn main:app --port 8000

    GET  /health                     -> {"status": "ok", "ready": bool}
    POST /query  {question, top_k?}  -> {"answer": str, "status": str,
                                         "sources": [{page, source, score, marker, ...}]}

`answer` has the [S1] markers stripped; each source carries its `marker` so a
client can still map claims to chunks. `status` is "answered" or "no_results".
Questions longer than QUESTION_MAX_CHARS are rejected with 422.

`create_app(settings=..., pipeline=...)` builds an independent service, e.g.
for tests or for embedding it in another program; `app` is the default one,
configured from .env.

Qdrant in local mode allows only one process at a time - run ingestion first,
then start this with a single worker. The service binds to 127.0.0.1 unless
told otherwise, and has no authentication: do not expose it publicly.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from rag.env import export_env_file
from rag.errors import RagError
from rag.log import show_progress
from rag.pipeline import Pipeline
from rag.settings import Settings, default_settings
from rag.step11_answer import strip_markers  # noqa: F401 - re-exported for callers

logger = logging.getLogger("rag.api")  # under "rag" so show_progress() prints it

# Bounds the cost of a single request (embedding + LLM prompt size).
QUESTION_MAX_CHARS = 4000


def _pipeline_for(app: FastAPI) -> Pipeline:
    """The app's one Pipeline, created on first use. The lock matters: requests run
    in a thread pool, and two Pipelines would open embedded Qdrant twice."""
    state = app.state
    with state.pipeline_lock:
        if state.pipeline is None:
            state.pipeline = Pipeline(settings=state.settings)
            state.owns_pipeline = True
        return state.pipeline


def get_pipeline(request: Request) -> Pipeline:
    """FastAPI dependency; tests swap it via app.dependency_overrides."""
    return _pipeline_for(request.app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up at startup so the first real request is fast. If it fails (e.g. the
    # collection has not been ingested yet) the service still starts and /health
    # stays green; /query then returns a clear 503.
    show_progress()
    if app.state.export_env:
        # Before the pipeline loads the embedding model (see rag/env.py).
        try:
            exported = export_env_file(app.state.settings or default_settings())
            if exported:
                logger.info(f"[startup] exported from .env: {', '.join(exported)}")
        except RagError as exc:
            logger.warning(f"[startup] .env not exported: {exc}")
    if os.getenv("RAG_API_WARMUP", "1") == "1":
        try:
            _pipeline_for(app).warm_up()
        except Exception as exc:  # noqa: BLE001 - reported back on /query
            logger.warning(f"[startup] not ready yet: {exc}")
    yield
    with app.state.pipeline_lock:
        if app.state.pipeline is not None and app.state.owns_pipeline:
            app.state.pipeline.close()
            app.state.pipeline = None


class QueryIn(BaseModel):
    question: str = Field(max_length=QUESTION_MAX_CHARS)
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


def health(request: Request) -> dict:
    pipeline = request.app.state.pipeline
    return {"status": "ok", "ready": pipeline is not None and pipeline.ready}


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


def create_app(settings: Optional[Settings] = None, pipeline: Optional[Pipeline] = None,
               export_env: bool = False) -> FastAPI:
    """A service with its own Pipeline. Without `pipeline`, one is created from
    `settings` (default: the project's .env) on first use and closed on shutdown;
    a pipeline passed in is left for the caller to close.

    export_env=True copies allow-listed .env keys (HF_HOME, proxies, ...) into
    os.environ at startup; only the default `app` does that (see rag/env.py)."""
    app = FastAPI(title="RAG toolkit service", lifespan=lifespan)
    app.state.settings = settings
    app.state.export_env = export_env
    app.state.pipeline = pipeline
    app.state.owns_pipeline = False
    app.state.pipeline_lock = threading.Lock()
    app.get("/health")(health)
    app.post("/query", response_model=AnswerOut)(query)
    return app


app = create_app(export_env=True)
