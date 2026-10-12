"""Errors the pipeline raises on purpose.

Every message says what went wrong *and* what to do about it, so the CLI, the
FastAPI service and the Streamlit UI can show it to the user as-is.
"""


class RagError(RuntimeError):
    """Base class for expected, user-fixable failures."""


class UnsupportedFileError(RagError):
    """Step 1: the input is missing, empty, or not a supported type."""


class ExtractionError(RagError):
    """Step 2: the file could not be opened or read."""


class EmptyDocumentError(RagError):
    """Steps 2-4: the file was read but produced no usable text."""


class EmbeddingProviderError(RagError):
    """Step 5: the embedding model could not be loaded or called."""


class VectorStoreError(RagError):
    """Step 6/9: Qdrant is unreachable, locked, missing, or incompatible."""


class GenerationError(RagError):
    """Step 10: the LLM could not be created or called."""
