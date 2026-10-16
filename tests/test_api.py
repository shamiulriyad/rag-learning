"""FastAPI service with the pipeline stubbed out."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from rag_kit import api  # noqa: E402
from rag_kit.errors import VectorStoreError  # noqa: E402
from rag_kit.pipeline import AnswerResult  # noqa: E402

SOURCES = [{"marker": "S1", "page": 3, "file": "g.pdf", "score": 0.8, "chunk_id": 2,
            "doc_id": "d", "text": "Nouns name things."}]


class StubPipeline:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def ask(self, question, k=None):
        self.calls.append((question, k))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def client_with():
    def _make(stub):
        api.app.dependency_overrides[api.get_pipeline] = lambda: stub
        return TestClient(api.app)  # no `with`: lifespan warm-up is skipped
    yield _make
    api.app.dependency_overrides.clear()


def test_health():
    response = TestClient(api.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ready": False}


def test_query_returns_answer_and_attributed_sources(client_with):
    stub = StubPipeline(AnswerResult("What is a noun?", "A naming word [S1].", "answered",
                                     SOURCES))
    response = client_with(stub).post("/query", json={"question": "What is a noun?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "A naming word."
    assert body["status"] == "answered"
    assert body["sources"] == [{"page": 3, "source": "g.pdf", "score": 0.8, "marker": "S1",
                                "chunk_id": 2, "text": "Nouns name things."}]
    assert stub.calls == [("What is a noun?", 3)]


def test_query_no_results(client_with):
    stub = StubPipeline(AnswerResult("q", "Nothing relevant.", "no_results", []))
    body = client_with(stub).post("/query", json={"question": "q"}).json()
    assert body["status"] == "no_results" and body["sources"] == []


def test_query_rejects_empty_question(client_with):
    stub = StubPipeline()
    assert client_with(stub).post("/query", json={"question": "  "}).status_code == 400
    assert stub.calls == []


def test_query_validates_top_k(client_with):
    assert client_with(StubPipeline()).post(
        "/query", json={"question": "q", "top_k": 0}).status_code == 422


def test_query_reports_pipeline_errors_as_503(client_with):
    stub = StubPipeline(error=VectorStoreError("Collection 'x' does not exist"))
    response = client_with(stub).post("/query", json={"question": "q"})
    assert response.status_code == 503
    assert "does not exist" in response.json()["detail"]


# --- question length limit ---------------------------------------------------------


def test_question_at_the_limit_is_accepted(client_with):
    stub = StubPipeline(AnswerResult("q", "Nothing relevant.", "no_results", []))
    question = "x" * api.QUESTION_MAX_CHARS
    assert client_with(stub).post("/query", json={"question": question}).status_code == 200
    assert stub.calls == [(question, None)]


def test_question_over_the_limit_is_rejected_before_the_pipeline(client_with):
    stub = StubPipeline()
    response = client_with(stub).post(
        "/query", json={"question": "x" * (api.QUESTION_MAX_CHARS + 1)})
    assert response.status_code == 422
    assert stub.calls == []


# --- application factory -------------------------------------------------------


def test_factory_apps_use_their_own_pipelines():
    first = StubPipeline(AnswerResult("q", "first [S1]", "answered", SOURCES))
    second = StubPipeline(AnswerResult("q", "second", "no_results", []))
    app_one, app_two = api.create_app(pipeline=first), api.create_app(pipeline=second)

    assert TestClient(app_one).post("/query", json={"question": "q"}).json()["answer"] == "first"
    assert TestClient(app_two).post("/query", json={"question": "q"}).json()["answer"] == "second"
    assert len(first.calls) == len(second.calls) == 1
    assert api.app.state.pipeline is None  # the default app was not touched


def test_factory_passes_settings_to_the_pipeline_it_creates(monkeypatch):
    from rag_kit.settings import Settings

    created = []

    class RecordingPipeline(StubPipeline):
        def __init__(self, settings=None):
            super().__init__(AnswerResult("q", "ok", "no_results", []))
            created.append(settings)

    monkeypatch.setattr(api, "Pipeline", RecordingPipeline)
    settings = Settings.load(".", environ={"COLLECTION_NAME": "api_only"})
    client = TestClient(api.create_app(settings=settings))

    client.post("/query", json={"question": "q"})
    client.post("/query", json={"question": "q"})
    assert created == [settings]  # created once, then reused


def test_concurrent_first_requests_create_one_pipeline(monkeypatch):
    import threading
    import time

    created = []

    class SlowPipeline:
        def __init__(self, settings=None):
            time.sleep(0.05)  # widen the window in which a second one could be made
            created.append(self)

    monkeypatch.setattr(api, "Pipeline", SlowPipeline)
    app = api.create_app()
    barrier = threading.Barrier(8)
    results = []

    def first_request():
        barrier.wait()
        results.append(api._pipeline_for(app))

    threads = [threading.Thread(target=first_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == 1
    assert all(result is created[0] for result in results)


def test_health_reports_ready_pipeline():
    class Ready:
        ready = True

    assert TestClient(api.create_app(pipeline=Ready())).get("/health").json() == {
        "status": "ok", "ready": True}


def test_shutdown_closes_only_a_pipeline_the_app_created(monkeypatch):
    closed = []

    class Closable(StubPipeline):
        def __init__(self, settings=None):
            super().__init__(AnswerResult("q", "ok", "no_results", []))

        def close(self):
            closed.append(self)

    monkeypatch.setattr(api, "Pipeline", Closable)
    app = api.create_app()
    with TestClient(app) as client:  # runs the lifespan; RAG_API_WARMUP=0 in tests
        client.post("/query", json={"question": "q"})
    assert len(closed) == 1 and app.state.pipeline is None

    injected = Closable()
    with TestClient(api.create_app(pipeline=injected)) as client:
        client.post("/query", json={"question": "q"})
    assert closed == [closed[0]]  # the caller's pipeline is left open
