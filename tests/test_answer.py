"""Steps 10-11 and the Pipeline: generation, attribution, empty retrieval."""

import pytest
from langchain_core.documents import Document

from rag_kit.errors import EmptyDocumentError, GenerationError
from rag_kit.pipeline import Pipeline
from rag_kit.step10_generate import NO_RESULTS_ANSWER, format_context, generate_answer
from rag_kit.step11_answer import build_sources, present, strip_markers
from tests.conftest import make_text_file


@pytest.mark.parametrize("raw, expected", [
    ("Nouns name things [S1].", "Nouns name things."),
    ("A [S1][S2] and B [S3].", "A and B."),
    ("No markers here.", "No markers here."),
    ("Ends with marker [S12]", "Ends with marker"),
])
def test_strip_markers(raw, expected):
    assert strip_markers(raw) == expected


def _scored():
    return [
        (Document(page_content="Nouns name things.",
                  metadata={"source_file": "g.pdf", "page_number": 3, "chunk_id": 7,
                            "doc_id": "d1"}), 0.82),
        (Document(page_content="Plain text chunk.",
                  metadata={"source_file": "n.md", "page_number": None, "chunk_id": 0}), 0.41),
    ]


def test_sources_carry_markers_pages_and_ids():
    sources = build_sources(_scored())
    assert [s["marker"] for s in sources] == ["S1", "S2"]
    assert sources[0] | {"text": None} == {"marker": "S1", "page": 3, "file": "g.pdf",
                                           "score": 0.82, "chunk_id": 7, "doc_id": "d1",
                                           "text": None}
    assert sources[1]["page"] is None


def test_context_labels_pages_only_when_known():
    context = format_context(_scored())
    assert "[S1] (g.pdf, page 3)" in context
    assert "[S2] (n.md)\n" in context


def test_generate_answer_with_fake_llm(fake_llm):
    assert generate_answer("What is a noun?", _scored(), llm=fake_llm).endswith("[S2].")


def test_no_retrieval_skips_the_llm(failing_llm):
    assert generate_answer("q", [], llm=failing_llm) == NO_RESULTS_ANSWER


def test_llm_failure_is_actionable(failing_llm):
    with pytest.raises(GenerationError, match="could not answer.*GOOGLE_API_KEY"):
        generate_answer("q", _scored(), llm=failing_llm)


def test_present_reports_status(capsys):
    assert present("q", "a", _scored())["status"] == "answered"
    assert present("q", NO_RESULTS_ANSWER, [])["status"] == "no_results"
    assert "Sources: none" in capsys.readouterr().out


# --- Pipeline end to end, with fakes ---------------------------------------------


@pytest.fixture
def pipeline(fake_embeddings, memory_client, fake_llm):
    return Pipeline(collection="pipe", embeddings=fake_embeddings, client=memory_client,
                    llm=fake_llm)


def test_pipeline_ingest_then_ask(pipeline, tmp_path):
    report = pipeline.ingest(make_text_file(tmp_path, "notes.txt", paragraphs=12))
    assert report["file"] == "notes.txt" and report["stored"] > 1

    result = pipeline.ask("What is a noun?", k=2)
    assert result.status == "answered"
    assert [s["marker"] for s in result.sources] == ["S1", "S2"]
    assert all(s["file"] == "notes.txt" for s in result.sources)
    assert "[S" not in result.answer_without_markers


def test_pipeline_no_relevant_results_does_not_call_llm(fake_embeddings, memory_client,
                                                         failing_llm, tmp_path):
    pipe = Pipeline(collection="pipe", embeddings=fake_embeddings, client=memory_client,
                    llm=failing_llm)
    pipe.ingest(make_text_file(tmp_path, "notes.txt", paragraphs=3))
    result = pipe.ask("anything", min_score=1.01)  # cosine can never exceed 1
    assert result.status == "no_results" and result.sources == []
    assert result.answer == NO_RESULTS_ANSWER


def test_pipeline_rejects_empty_question(pipeline):
    with pytest.raises(ValueError, match="empty"):
        pipeline.ask("   ")


def test_pipeline_rejects_document_without_text(pipeline, tmp_path):
    path = tmp_path / "tiny.txt"
    path.write_text("too short", encoding="utf-8")
    with pytest.raises(EmptyDocumentError, match="No usable text"):
        pipeline.ingest(path)


def test_pipeline_reingest_replaces(pipeline, tmp_path):
    path = make_text_file(tmp_path, "notes.txt", paragraphs=12)
    first = pipeline.ingest(path)
    make_text_file(tmp_path, "notes.txt", paragraphs=4, topic="verb")
    second = pipeline.ingest(path)
    assert second["removed_outdated"] > 0
    assert pipeline.documents() == {"notes.txt": second["stored"]}
    assert second["stored"] < first["stored"]
