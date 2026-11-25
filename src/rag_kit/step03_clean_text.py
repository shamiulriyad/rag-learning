"""STEP 3 - Text cleaning.

PDF text arrives with hard line breaks, hyphen-split words, ligature
characters, repeated headers/footers, stray page numbers and table-of-contents
pages. All of that pollutes the embeddings, so it gets removed before chunking.
"""

import logging
import re
from collections import Counter
from typing import List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SINGLE_NEWLINE = re.compile(r"(?<![.!?:;।])\n(?![\n\-\u2022\d])")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s*)?[\divxlIVXL]{1,4}\s*$", re.MULTILINE | re.IGNORECASE)
_SPACES = re.compile(r"[ \t]{2,}")
_BLANK_LINES = re.compile(r"\n{3,}")
# Typographic ligatures (U+FB00-FB06) that PDFs emit as one character, so
# "efficient" arrives as "ef\ufb01cient". Mapped one by one: NFKC would also fold
# superscripts and turn "n\u00b2" into "n2".
_LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
                            "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})
# A table-of-contents entry ends in a dot leader, optionally followed by the
# page number: "1.1 Introduction . . . . . . 3".
_DOT_LEADER = re.compile(r"(?:\.[ \t]?){5,}[ \t]*[\dIVXLCivxlc]*[ \t]*$")


def is_table_of_contents(text: str, min_entries: int = 5, min_share: float = 0.2) -> bool:
    """True for a page made of dot-leader entries. Such pages match every
    question that names a chapter, and crowd the real content out of the results."""
    lines = [line for line in text.splitlines() if line.strip()]
    entries = sum(1 for line in lines if _DOT_LEADER.search(line))
    return entries >= min_entries and entries >= min_share * len(lines)


def clean_text(text: str) -> str:
    text = text.translate(_LIGATURES)            # "\ufb01" -> "fi"
    text = text.replace("\u00ad", "")            # soft hyphen
    text = text.replace("\ufeff", "")            # BOM
    text = _CONTROL_CHARS.sub(" ", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)      # "informa-\ntion" -> "information"
    text = _PAGE_NUMBER_LINE.sub("", text)
    text = _SINGLE_NEWLINE.sub(" ", text)        # unwrap mid-sentence line breaks
    text = _SPACES.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _find_repeating_lines(docs: List[Document], threshold: float = 0.6) -> set:
    """Lines that show up on most pages are headers/footers, not content."""
    if len(docs) < 4:
        return set()

    counter = Counter()
    for doc in docs:
        for line in {ln.strip() for ln in doc.page_content.splitlines() if ln.strip()}:
            if len(line) < 80:
                counter[line] += 1

    cutoff = len(docs) * threshold
    return {line for line, count in counter.items() if count >= cutoff}


def _drop_lines(text: str, boilerplate: set) -> str:
    """Blank out whole lines that are boilerplate. Matching whole lines (not
    substrings) keeps a short header like "Chapter" from being cut out of the
    sentences that happen to contain it."""
    if not boilerplate:
        return text
    return "\n".join("" if line.strip() in boilerplate else line for line in text.split("\n"))


def clean_documents(docs: List[Document], min_chars: int = 50) -> List[Document]:
    """Return cleaned copies; the input Documents are left untouched."""
    boilerplate = _find_repeating_lines(docs)

    cleaned: List[Document] = []
    contents_pages = 0
    for doc in docs:
        # PDF pages only: a text file is a single Document, and dropping it
        # because it opens with a contents list would lose the whole file.
        if doc.metadata.get("page_number") is not None and is_table_of_contents(doc.page_content):
            contents_pages += 1
            continue
        body = clean_text(_drop_lines(doc.page_content, boilerplate))
        if len(body) < min_chars:      # blank or near-blank page
            continue

        cleaned.append(Document(id=doc.id, page_content=body, metadata=dict(doc.metadata)))

    dropped = len(docs) - len(cleaned)
    contents_note = f" ({contents_pages} table of contents)" if contents_pages else ""
    logger.info(f"[3] Cleaned    : {len(cleaned)} pages kept, {dropped} dropped{contents_note}, "
                f"{len(boilerplate)} repeating header/footer lines removed")
    return cleaned
