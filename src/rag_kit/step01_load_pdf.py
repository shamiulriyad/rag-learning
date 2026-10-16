"""STEP 1 - Input document.

Validate the file before anything else, so a wrong path fails here
instead of halfway through the pipeline. PDF, plain text and Markdown are
supported (see rag_kit.settings.SUPPORTED_EXTENSIONS).
"""

import logging
from pathlib import Path

from rag_kit.errors import UnsupportedFileError
from rag_kit.settings import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


def load_document(path) -> Path:
    path = Path(path).expanduser().resolve()

    if not path.exists():
        raise UnsupportedFileError(f"File not found: {path}")
    if not path.is_file():
        raise UnsupportedFileError(f"Not a file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{path.suffix or '(none)'}' for {path.name}. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if path.stat().st_size == 0:
        raise UnsupportedFileError(f"File is empty: {path.name}")

    size_kb = path.stat().st_size / 1024
    logger.info(f"[1] Document   : {path.name} ({size_kb:.1f} KB)")
    return path


# Kept for scripts written against the original PDF-only pipeline.
load_pdf = load_document
