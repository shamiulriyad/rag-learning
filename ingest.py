"""Ingestion pipeline - steps 1 to 6. Shortcut for `python cli.py ingest`.

    python ingest.py                       # uses PDF_PATH from .env
    python ingest.py data/book.pdf notes.md
    python ingest.py --pdf data/book.pdf   # original flag, still accepted
    python ingest.py data/book.pdf --recreate
"""

import sys

import cli

if __name__ == "__main__":
    sys.exit(cli.main(["ingest", *sys.argv[1:]]))
