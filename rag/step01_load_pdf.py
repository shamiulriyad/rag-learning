"""STEP 1 - Input document.

Validate the file before anything else, so a wrong path fails here
instead of halfway through the pipeline. PDF, plain text and Markdown are
supported (see config.SUPPORTED_EXTENSIONS).
"""

from pathlib import Path

import config
from rag.errors import UnsupportedFileError


def load_document(path) -> Path:
    path = Path(path).expanduser().resolve()

    if not path.exists():
        raise UnsupportedFileError(f"File not found: {path}")
    if not path.is_file():
        raise UnsupportedFileError(f"Not a file: {path}")
    if path.suffix.lower() not in config.SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{path.suffix or '(none)'}' for {path.name}. "
            f"Supported: {', '.join(config.SUPPORTED_EXTENSIONS)}."
        )
    if path.stat().st_size == 0:
        raise UnsupportedFileError(f"File is empty: {path.name}")

    size_kb = path.stat().st_size / 1024
    print(f"[1] Document   : {path.name} ({size_kb:.1f} KB)")
    return path


# Kept for scripts written against the original PDF-only pipeline.
load_pdf = load_document
