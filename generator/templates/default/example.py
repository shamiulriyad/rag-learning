"""Ingest one document and ask a question about it with rag-kit.

    python example.py data/your-document.pdf "What is this document about?"

Run it inside this project (the folder with rag-kit.toml) after creating
.env from .env.example. Asking needs GOOGLE_API_KEY in .env.
"""

import sys

from rag_kit import Pipeline, Settings
from rag_kit.env import export_env_file
from rag_kit.errors import RagError
from rag_kit.log import show_progress


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    document, question = argv[1], argv[2]

    settings = Settings.load()  # this project's .env, found from rag-kit.toml
    export_env_file(settings)   # HF_HOME, proxies etc. from .env, as the rag-kit command does
    show_progress()             # print each pipeline step

    pipeline = Pipeline(settings=settings)
    try:
        pipeline.ingest(document)        # re-ingesting the same file replaces its chunks
        result = pipeline.ask(question)
    except RagError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        pipeline.close()

    print()
    print(result.answer_without_markers)
    for source in result.sources:
        page = f", page {source['page']}" if source["page"] else ""
        print(f"[{source['marker']}] {source['file']}{page} (score {source['score']:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
