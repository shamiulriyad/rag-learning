"""Library code logs instead of printing; applications choose to show it."""

import json
import logging

import pytest
from langchain_core.documents import Document

import cli
from rag.log import _CurrentStdout, show_progress
from rag.pipeline import Pipeline
from tests.conftest import make_text_file


@pytest.fixture
def rag_logger():
    """The "rag" logger as a library user gets it (other tests may have run the CLI,
    which turns progress on); restored afterwards."""
    logger = logging.getLogger("rag")
    saved = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = [h for h in logger.handlers if not isinstance(h, _CurrentStdout)]
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    yield logger
    logger.handlers, logger.level, logger.propagate = saved


def _ingest_and_ask(tmp_path, fake_embeddings, memory_client, fake_llm):
    pipe = Pipeline(collection="log", embeddings=fake_embeddings, client=memory_client,
                    llm=fake_llm)
    pipe.ingest(make_text_file(tmp_path, "notes.txt", paragraphs=8))
    pipe.ask("What is a noun?", k=2)


def test_library_writes_nothing_to_stdout_or_stderr(rag_logger, tmp_path, capsys,
                                                    fake_embeddings, memory_client, fake_llm):
    _ingest_and_ask(tmp_path, fake_embeddings, memory_client, fake_llm)
    assert capsys.readouterr() == ("", "")


def test_steps_report_progress_through_logging(rag_logger, tmp_path, caplog,
                                               fake_embeddings, memory_client, fake_llm):
    with caplog.at_level(logging.INFO, logger="rag"):
        _ingest_and_ask(tmp_path, fake_embeddings, memory_client, fake_llm)
    messages = [r.getMessage() for r in caplog.records]
    for prefix in ("[1] Document", "[2] Extracted", "[3] Cleaned", "[4] Chunked",
                   "[6] Qdrant", "[8] Query vec", "[9] Retrieved", "[10] Gemini"):
        assert any(m.startswith(prefix) for m in messages), prefix
    assert all(r.name.startswith("rag.") for r in caplog.records)


def test_show_progress_prints_message_text_once(rag_logger, capsys):
    show_progress()
    show_progress()  # calling twice must not duplicate output
    logging.getLogger("rag.step01_load_pdf").info("[1] Document   : a.txt (1.0 KB)")
    assert capsys.readouterr().out == "[1] Document   : a.txt (1.0 KB)\n"


def test_cli_json_sends_logged_progress_to_stderr(rag_logger, monkeypatch, capsys):
    class LoggingPipeline:
        def __init__(self, *a, **kw):
            pass

        def search(self, question, **kw):
            logging.getLogger("rag.step09_retrieve").info("[9] Retrieved  : 1 chunks")
            return [(Document(page_content="t", metadata={"source_file": "a.md"}), 0.5)]

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", LoggingPipeline)
    assert cli.main(["search", "q", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["file"] == "a.md"   # stdout is only JSON
    assert "[9] Retrieved" in captured.err


def test_cli_without_json_prints_progress_to_stdout(rag_logger, monkeypatch, capsys):
    class LoggingPipeline:
        def __init__(self, *a, **kw):
            pass

        def search(self, question, **kw):
            logging.getLogger("rag.step09_retrieve").info("[9] Retrieved  : 0 chunks")
            return []

        def close(self):
            pass

    monkeypatch.setattr("rag.pipeline.Pipeline", LoggingPipeline)
    assert cli.main(["search", "q"]) == 0
    assert capsys.readouterr().out == "[9] Retrieved  : 0 chunks\nNo chunks retrieved.\n"
