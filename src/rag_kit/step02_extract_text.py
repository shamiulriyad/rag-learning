"""STEP 2 - Text extraction.

PDFs become one LangChain Document per page, with the 1-based page number in
metadata - that number is what step 11 cites. Text and Markdown files become a
single Document with no page number.

Every Document carries the same metadata keys:
    source_file   file name, used to replace / delete a document later
    doc_id        content hash, changes when the file changes
    file_type     "pdf", "txt" or "md"
    page          0-based page index (None for text files)
    page_number   1-based page number (None for text files)

Optional font repair (PDF_FONT_REPAIR=true or font_repair=True): some PDFs embed
subset fonts with no ToUnicode map, and every extractor then returns scrambled
glyph codes like `& ? ! & &`. `pdf_font_repair.repair_page` undoes the specific
substitution cipher of this project's grammar PDF. Leave it off for ordinary
PDFs.

After extraction every PDF page is scored (alphabetic ratio + English-word
ratio). Table-of-contents pages are counted separately (step 3 drops them).
Of the other low-scoring pages, those with very few letters look scrambled and
are reported as a warning - that is the point where OCR would be the next
step. The rest are usually diagrams, formulas or tables, and are only listed.
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from rag_kit.errors import ExtractionError
from rag_kit.pdf_font_repair import is_readable, repair_page, text_quality
from rag_kit.settings import Settings, default_settings
from rag_kit.step03_clean_text import is_table_of_contents

logger = logging.getLogger(__name__)

# Below this share of letters an unreadable page looks scrambled rather than
# like a diagram or formula page. Measured: scrambled-font pages score 0.01-0.35,
# diagram and formula pages of a typeset book 0.60-0.68.
SCRAMBLED_ALPHA_RATIO = 0.4


def document_id(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def extract_text(path: Path, font_repair: Optional[bool] = None,
                 settings: Optional[Settings] = None) -> List[Document]:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        if font_repair is None:
            font_repair = (settings or default_settings()).pdf_font_repair
        return _extract_pdf(path, font_repair)
    return _extract_plain_text(path)


def _metadata(path: Path, doc_id: str, page: Optional[int]) -> dict:
    return {
        "source_file": path.name,
        "doc_id": doc_id,
        "file_type": path.suffix.lower().lstrip("."),
        "page": page,
        "page_number": None if page is None else page + 1,
    }


def _extract_plain_text(path: Path) -> List[Document]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            f"{path.name} is not valid UTF-8 text ({exc.reason} at byte {exc.start}). "
            "Re-save it as UTF-8 and ingest again."
        ) from exc
    except OSError as exc:
        raise ExtractionError(f"Could not read {path.name}: {exc}") from exc

    logger.info(f"[2] Extracted  : 1 text document, {len(text):,} characters")
    return [Document(page_content=text, metadata=_metadata(path, document_id(path), None))]


def _extract_pdf(path: Path, font_repair: bool) -> List[Document]:
    import pymupdf

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # pymupdf raises several types for broken files
        raise ExtractionError(f"Could not open {path.name} as a PDF: {exc}") from exc

    if doc.needs_pass:
        doc.close()
        raise ExtractionError(
            f"{path.name} is password-protected. Decrypt it first (e.g. `qpdf --decrypt`)."
        )

    doc_id = document_id(path)
    pages: List[Document] = []
    readable = contents = blank = 0
    scrambled: List[tuple] = []
    low_text: List[tuple] = []

    try:
        for index in range(doc.page_count):
            page = doc[index]
            text = repair_page(page) if font_repair else page.get_text("text")
            page_number = index + 1

            if len(text.strip()) < 20:
                blank += 1
            elif is_table_of_contents(text):
                contents += 1
            elif is_readable(text):
                readable += 1
            else:
                alpha_ratio, word_ratio = text_quality(text)
                bucket = scrambled if alpha_ratio < SCRAMBLED_ALPHA_RATIO else low_text
                bucket.append((round(word_ratio, 2), round(alpha_ratio, 2), page_number))

            pages.append(Document(page_content=text, metadata=_metadata(path, doc_id, index)))
    except Exception as exc:
        raise ExtractionError(f"Text extraction failed on {path.name}: {exc}") from exc
    finally:
        doc.close()

    total_chars = sum(len(p.page_content) for p in pages)
    logger.info(f"[2] Extracted  : {len(pages)} pages, {total_chars:,} characters"
                f"{' (font repair on)' if font_repair else ''}")
    logger.info(f"    quality    : {readable} readable, {contents} table of contents, "
                f"{len(low_text)} mostly diagrams/formulas, {len(scrambled)} scrambled, "
                f"{blank} blank")

    if low_text:
        logger.info(f"    note       : {len(low_text)} page(s) are mostly diagrams, formulas "
                    f"or tables and are kept: {_page_list(low_text)}")
    if scrambled:
        logger.warning(f"    ! {len(scrambled)} page(s) look scrambled: {_page_list(scrambled)}")
        if font_repair:
            logger.warning("      The maps in pdf_font_repair.py fit one specific PDF; "
                           "for this one, use OCR (e.g. ocrmypdf).")
        else:
            logger.warning("      Check the text. If it is scanned or unreadable, run OCR first "
                           "(e.g. ocrmypdf). PDF_FONT_REPAIR=true fixes only the one book "
                           "described in pdf_font_repair.py.")

    if total_chars < 100:
        logger.warning("    ! Almost no text found - this PDF is probably a scan. Add OCR "
                       "before this pipeline can work.")

    return pages


def _page_list(pages: List[tuple], limit: int = 10) -> str:
    """'p3, p7, p12' for the worst pages first, '(+N more)' past the limit."""
    shown = ", ".join(f"p{pn}" for _, _, pn in sorted(pages)[:limit])
    return shown + (f" (+{len(pages) - limit} more)" if len(pages) > limit else "")
