"""Steps 1-4: input validation, extraction, cleaning, chunking."""

import pytest
from langchain_core.documents import Document

from rag.errors import ExtractionError, UnsupportedFileError
from rag.step01_load_pdf import load_document
from rag.step02_extract_text import extract_text
from rag.step03_clean_text import clean_documents, clean_text
from rag.step04_chunking import chunk_documents

# --- step 1 -------------------------------------------------------------------


def test_load_document_accepts_supported_types(tmp_path):
    for name in ("a.pdf", "b.TXT", "c.md"):
        path = tmp_path / name
        path.write_bytes(b"x")
        assert load_document(path) == path.resolve()


@pytest.mark.parametrize("name, content, message", [
    ("missing.pdf", None, "File not found"),
    ("sheet.xlsx", b"x", "Unsupported file type"),
    ("empty.txt", b"", "File is empty"),
])
def test_load_document_rejects_bad_input(tmp_path, name, content, message):
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    with pytest.raises(UnsupportedFileError, match=message):
        load_document(path)


# --- step 2 -------------------------------------------------------------------


def _make_pdf(path, pages):
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def test_extract_pdf_keeps_page_numbers_and_metadata(tmp_path):
    pdf = _make_pdf(tmp_path / "guide.pdf", ["First page about nouns.", "Second page about verbs."])
    pages = extract_text(pdf, font_repair=False)

    assert [p.metadata["page_number"] for p in pages] == [1, 2]
    assert [p.metadata["page"] for p in pages] == [0, 1]
    assert "nouns" in pages[0].page_content and "verbs" in pages[1].page_content
    meta = pages[0].metadata
    assert meta["source_file"] == "guide.pdf" and meta["file_type"] == "pdf"
    assert len(meta["doc_id"]) == 16 and pages[1].metadata["doc_id"] == meta["doc_id"]


def test_font_repair_is_off_by_default_and_used_only_when_asked(tmp_path, monkeypatch):
    import rag.step02_extract_text as step02
    calls = []
    monkeypatch.setattr(step02, "repair_page", lambda page: calls.append(page) or "repaired text")
    pdf = _make_pdf(tmp_path / "x.pdf", ["Plain text page."])

    assert "Plain text page" in extract_text(pdf)[0].page_content
    assert calls == []
    assert extract_text(pdf, font_repair=True)[0].page_content == "repaired text"
    assert len(calls) == 1


def test_extract_plain_text_and_markdown(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome markdown text.", encoding="utf-8")
    [doc] = extract_text(path)
    assert doc.page_content.startswith("# Title")
    assert doc.metadata["page_number"] is None and doc.metadata["file_type"] == "md"


def test_extract_rejects_non_utf8_text(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes("caf\xe9 cr\xe8me".encode("latin-1"))
    with pytest.raises(ExtractionError, match="not valid UTF-8"):
        extract_text(path)


def test_extract_reports_broken_pdf(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf at all")
    with pytest.raises(ExtractionError, match="Could not open broken.pdf"):
        extract_text(path)


# --- step 3 -------------------------------------------------------------------


def test_clean_text_repairs_pdf_artifacts():
    raw = "This is infor-\nmation that\nwraps mid sentence.\n\n\n\n12\nNext   paragraph."
    cleaned = clean_text(raw)
    assert cleaned.startswith("This is information that wraps mid sentence.")
    assert cleaned.endswith("Next paragraph.")
    assert "12" not in cleaned and "  " not in cleaned and "\n\n\n" not in cleaned


def test_clean_documents_drops_headers_and_blank_pages():
    body = "Real content about grammar that is long enough to keep on the page. "
    docs = [Document(page_content=f"BOOK HEADER\n{body * 2}", metadata={"page_number": i})
            for i in range(1, 5)]
    docs.append(Document(page_content="BOOK HEADER\nshort", metadata={"page_number": 5}))

    cleaned = clean_documents(docs)

    assert [d.metadata["page_number"] for d in cleaned] == [1, 2, 3, 4]
    assert all("BOOK HEADER" not in d.page_content for d in cleaned)


def test_clean_documents_keeps_header_words_inside_body_text():
    # Regression: a repeated header line was removed with str.replace, which also
    # cut the same word out of every sentence that contained it.
    docs = [Document(page_content=f"Chapter\nThe Chapter on nouns explains page {i} content "
                                  "in detail, enough text to keep.", metadata={"page_number": i})
            for i in range(1, 6)]

    cleaned = clean_documents(docs)

    assert [d.page_content for d in cleaned] == [
        f"The Chapter on nouns explains page {i} content in detail, enough text to keep."
        for i in range(1, 6)
    ]


def test_clean_documents_does_not_modify_its_input():
    original = "HEADER\n" + "Real content about grammar that is long enough to keep. " * 2
    docs = [Document(page_content=original, metadata={"page_number": i}) for i in range(1, 5)]

    cleaned = clean_documents(docs)

    assert all(d.page_content == original for d in docs)
    assert all("HEADER" not in d.page_content for d in cleaned)
    assert cleaned[0].metadata == {"page_number": 1}
    assert cleaned[0].metadata is not docs[0].metadata


# --- step 4 -------------------------------------------------------------------


def test_chunking_preserves_metadata_and_numbers_chunks():
    meta = {"source_file": "a.pdf", "doc_id": "abc", "page_number": 7, "file_type": "pdf"}
    text = " ".join(f"Sentence number {i} about nouns." for i in range(80))
    chunks = chunk_documents([Document(page_content=text, metadata=dict(meta))], 200, 40)

    assert len(chunks) > 5
    assert [c.metadata["chunk_id"] for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert len(chunk.page_content) <= 200
        assert {k: chunk.metadata[k] for k in meta} == meta
        assert "start_index" in chunk.metadata
