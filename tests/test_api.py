"""FastAPI service with the pipeline stubbed out."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from rag.errors import VectorStoreError  # noqa: E402
from rag.pipeline import AnswerResult  # noqa: E402

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
        main.app.dependency_overrides[main.get_pipeline] = lambda: stub
        return TestClient(main.app)  # no `with`: lifespan warm-up is skipped
    yield _make
    main.app.dependency_overrides.clear()


def test_health():
    response = TestClient(main.app).get("/health")
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
