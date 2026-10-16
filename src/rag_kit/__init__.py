"""rag-kit: a reusable RAG toolkit, one module per step of the pipeline.

    from rag_kit import Pipeline, Settings

    pipeline = Pipeline(settings=Settings.load("path/to/project"))

1  step01_load_pdf        Input document (.pdf, .txt, .md)
2  step02_extract_text    Text extraction
3  step03_clean_text      Text cleaning
4  step04_chunking        Chunking
5  step05_embedding       Embedding model
6  step06_vector_store    Store in Qdrant
7  (the CLI / API)        User question
8  step08_query_embedding Query embedding
9  step09_retrieve        Retrieve relevant chunks
10 step10_generate        Gemini
11 step11_answer          Answer + sources

Steps report progress through logging (see rag_kit/log.py), never print().
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from rag_kit.errors import RagError
from rag_kit.settings import Settings

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("rag-kit")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0+unknown"

__all__ = ["AnswerResult", "Pipeline", "RagError", "Settings", "__version__"]


def __getattr__(name):
    # Pipeline pulls in LangChain and Qdrant; load it only when asked for, so
    # `import rag_kit` and `rag-kit --help` stay fast.
    if name in ("Pipeline", "AnswerResult"):
        from rag_kit import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module 'rag_kit' has no attribute {name!r}")
