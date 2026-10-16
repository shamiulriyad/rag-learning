# rag-kit

A reusable, developer-focused RAG toolkit for document ingestion, retrieval,
and source-grounded answers. Index PDF, text and Markdown files into Qdrant,
then ask questions and get answers that cite the chunks (and PDF page numbers)
they came from.

Every pipeline step is its own module under [`src/rag_kit/`](https://github.com/shamiulriyad/rag-learning/tree/main/src/rag_kit), so
you can read, test and swap each one. Use it from the `rag-kit` command, from
Python, through an optional FastAPI service, or through an optional Streamlit
test UI.

![Pipeline: ingest (load, extract, clean, chunk, embed, store in Qdrant) and query (question, embed, retrieve, Gemini, answer with sources); CLI, FastAPI and Streamlit all call the same Pipeline](https://raw.githubusercontent.com/shamiulriyad/rag-learning/main/docs/architecture.svg)

> **Status:** 0.1.0, not yet published to PyPI. Install from a checkout (see
> below). Upgrading from the script-based version? See
> [CHANGELOG.md](https://github.com/shamiulriyad/rag-learning/blob/main/CHANGELOG.md) for the old-to-new command table.

## Start a new project

`rag-kit-dev`, the npm package in [`generator/`](https://github.com/shamiulriyad/rag-learning/tree/main/generator),
creates a project folder (settings template, `data/`, an example) and a `.venv`
with rag-kit installed. It explains the local-vs-Gemini embedding choice before
installing anything and never creates `.env` or asks for an API key.

```bash
npx rag-kit-dev my-rag                     # once rag-kit-dev and rag-kit are published
```

Until then, run it from a checkout against a locally built wheel (testing only):

```bash
uv build --out-dir dist
node generator/bin/rag-kit-dev.js my-rag --embeddings gemini --package-spec dist/rag_kit-0.1.0-py3-none-any.whl
```

## What it does

| Step | Module | Notes |
| ---- | ------ | ----- |
| 1 Load | `step01_load_pdf.py` | `.pdf`, `.txt`, `.md`; validates before any work |
| 2 Extract | `step02_extract_text.py` | one Document per PDF page; optional font repair |
| 3 Clean | `step03_clean_text.py` | unwrap lines, join hyphenation, drop headers/footers |
| 4 Chunk | `step04_chunking.py` | recursive splitter, overlap, `chunk_id` per document |
| 5 Embed | `step05_embedding.py` | local Hugging Face model (default `BAAI/bge-m3`) or Gemini |
| 6 Store | `step06_vector_store.py` | Qdrant, embedded on disk or a server |
| 8–9 Retrieve | `step08`, `step09` | cosine search, optional minimum score |
| 10 Generate | `step10_generate.py` | Gemini, context-only, tags claims `[S1]`, `[S2]`… |
| 11 Answer | `step11_answer.py` | answer plus the sources behind each marker |

Step 7 (the question) comes from the CLI, the API or the UI.
[`pipeline.py`](https://github.com/shamiulriyad/rag-learning/blob/main/src/rag_kit/pipeline.py) wires the steps together; the CLI,
API and UI all use it. See [docs/pipeline.md](https://github.com/shamiulriyad/rag-learning/blob/main/docs/pipeline.md) for per-step
notes.

## Prerequisites

- **Python 3.11 or 3.12** (the package refuses other versions for now).
- A **Gemini API key** for answer generation
  ([get one](https://aistudio.google.com/app/apikey)). Ingestion and retrieval
  with the default local embeddings need no key.
- For local embeddings: disk space for PyTorch and the model. `BAAI/bge-m3` is
  about 2.2 GB and is downloaded to the Hugging Face cache on first use.
- Optional: Docker, if you prefer a Qdrant server to the embedded store.

## Install

```bash
py -3.11 -m venv .venv            # macOS/Linux: python3.11 -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
python -m pip install -U pip

# From a checkout of this repository:
pip install -e ".[local,gemini]"  # local embeddings + Gemini answers
```

Choose extras for what you need:

| Extra | Adds | Needed for |
| ----- | ---- | ---------- |
| *(none)* | LangChain core, Qdrant, PyMuPDF | ingestion/retrieval plumbing, `rag-kit check` |
| `local` | sentence-transformers (pulls in PyTorch) | `EMBEDDING_PROVIDER=huggingface` (default) |
| `gemini` | langchain-google-genai | answers, and `EMBEDDING_PROVIDER=google` |
| `api` | FastAPI, uvicorn | `rag-kit serve` |
| `ui` | Streamlit | `rag-kit ui` |
| `dev` | pytest, httpx, ruff (+ `api`) | running the tests |
| `all` | `local`, `gemini`, `api`, `ui` | everything |

**Linux and CPU-only PyTorch (recommended):** on Linux, PyTorch from PyPI
pulls in CUDA libraries (several GB). For CPU-only local embeddings, install
the CPU build from PyTorch's own index **first**, in the same virtual
environment, then rag-kit:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[local,gemini]"           # keeps the CPU torch that is installed

# with uv instead of pip:
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -e ".[local,gemini]"
```

This works on x86_64 and aarch64 Linux with Python 3.11 and 3.12. Later
`pip install -U "rag-kit[local]"` keeps the CPU build as long as it satisfies
the requirement; upgrading torch itself (`pip install -U torch`) without the
`--index-url` above would switch to the CUDA build. If a CUDA build is already
installed, start from a fresh virtual environment: reinstalling torch over it
leaves the `nvidia-*` packages behind. With an NVIDIA GPU you want to use,
skip the first command.

On Windows and macOS, PyTorch from PyPI does not pull in CUDA libraries, so no
extra step is needed.

## Set up a project

A project is a folder with a `rag-kit.toml` marker file. It holds your `.env`,
your documents and the embedded Qdrant store; nothing is ever written inside
the installed package. This repository is itself a project.

```bash
mkdir my-rag && cd my-rag
# create the marker (its contents are reserved; an empty file is fine)
echo "# rag-kit project" > rag-kit.toml
# copy .env.example from this repository to my-rag/.env, then set GOOGLE_API_KEY
rag-kit check                      # settings, dependencies, vector store
rag-kit check --deep               # also loads the embedding model, compares dimensions
```

Commands find the project like this:

1. `--project DIR` (any command; no marker needed),
2. else the `RAG_PROJECT_DIR` environment variable,
3. else the nearest folder at or above the current directory that contains
   `rag-kit.toml`.

If none applies, the command stops with an error instead of creating a store
somewhere unexpected. Relative paths in `.env` (`QDRANT_PATH`, `PDF_PATH`) are
resolved from the project folder, so commands behave the same from any
subfolder.

## Configure

Settings come from the project's `.env` (or the file named by `RAG_ENV_FILE`).
Environment variables win over `.env`, and command-line flags such as
`--collection`, `-k` and `--min-score` win over both.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `GOOGLE_API_KEY` | – | Gemini key (generation; embeddings if provider is `google`) |
| `LLM_MODEL` | `gemini-2.5-flash` | Gemini model for answers |
| `TEMPERATURE` | `0.2` | LLM temperature |
| `EMBEDDING_PROVIDER` | `huggingface` | `huggingface` (local) or `google` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 1024-dim; `models/gemini-embedding-001` for `google` |
| `EMBEDDING_DIM` | auto | set only to skip auto-detection |
| `QDRANT_PATH` | – | embedded store folder, e.g. `qdrant_data` (wins over URL) |
| `QDRANT_URL` / `QDRANT_API_KEY` | `http://localhost:6333` | Qdrant server |
| `COLLECTION_NAME` | `pdf_rag` | collection to read and write |
| `PDF_PATH` | `data/sample.pdf` | file for `ingest` with no arguments |
| `PDF_FONT_REPAIR` | `false` | repair scrambled-glyph PDFs (see below) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `150` | chunking |
| `TOP_K` | `4` | chunks per question |
| `MIN_SCORE` | – | drop chunks below this cosine score |
| `EMBED_BATCH_SIZE` / `EMBED_SLEEP` | `90` / `0` (`60` for google) | ingestion batching |
| `RAG_PROJECT_DIR` | – | project folder (environment only) |
| `RAG_ENV_FILE` | `<project>/.env` | use another settings file (environment only) |
| `RAG_EXPORT_ENV` | – | extra `.env` names to export, comma-separated (see below) |

Without `QDRANT_PATH`, rag-kit connects to a Qdrant server at `QDRANT_URL`.
A collection is tied to the embedding model that built it. If the model's
dimension does not match the collection, every command stops with an error
instead of writing incompatible vectors.

### Variables for other libraries (`HF_HOME`, proxies)

Some libraries read only the process environment: Hugging Face reads `HF_HOME`
when it is first imported, and HTTP clients read proxy variables. So that
these can live in `.env` too, the `rag-kit` command, `rag-kit serve` (the
default `rag_kit.api:app`) and `rag-kit ui` copy an **allow-list** of `.env`
keys into the environment at startup:

- `HF_*`, `HUGGINGFACE_*`, `TRANSFORMERS_*`, `SENTENCE_TRANSFORMERS_*`, `TORCH_*`,
  `TOKENIZERS_PARALLELISM`, `CUDA_VISIBLE_DEVICES`, `OMP_NUM_THREADS`
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `ALL_PROXY` (either case),
  `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `CURL_CA_BUNDLE`
- any names you list in `RAG_EXPORT_ENV=NAME1,NAME2`

rag-kit's own settings, including `GOOGLE_API_KEY` and `QDRANT_API_KEY`, and
any `RAG_*` variable are **never** exported, even if listed. Variables already
set in the environment win, empty values are skipped, and only names are ever
printed (`rag-kit check` lists them). `HF_TOKEN` is a secret but is exported,
because Hugging Face reads it only from the environment.

Importing `rag_kit`, building a `Pipeline` or calling `Settings.load()` never
changes the environment. In your own program, call
`rag_kit.env.export_env_file(settings)` before the first local embedding is
created if you want the same behaviour.

## Ingest documents

```bash
rag-kit ingest data/book.pdf notes.md      # several files at once
rag-kit ingest                             # PDF_PATH from .env
rag-kit ingest report.pdf --collection experiments
rag-kit ingest scanned-font.pdf --font-repair on
rag-kit ingest --project ~/my-rag report.pdf
```

- **Re-ingesting replaces.** Chunks get IDs derived from file name, content
  hash and position. Ingesting a file again overwrites its chunks and removes
  any older ones with the same file name, so nothing is duplicated. Two
  different files with the same name in one collection count as one document.
- **Delete one document:** `rag-kit delete report.pdf` (asks first; `-y` to skip).
- **List documents:** `rag-kit documents`, or `--json` for
  `{"collection": str, "total_chunks": int, "documents": [{"file": str, "chunks": int}]}`
  (stable schema; files sorted by name).
- **Start over:** `rag-kit ingest file.pdf --recreate` drops the whole
  collection first. Needed after changing the embedding model.
- **File names starting with `-`** look like options to the CLI. Write
  `./-name.pdf`, or put `--` before the files:
  `rag-kit ingest --font-repair on -- -Free-English-Grammar.pdf`.

## Ask questions

```bash
rag-kit ask "What is a countable noun?"
rag-kit ask                                  # interactive, 'exit' to quit
rag-kit ask "..." --show-chunks              # also print each chunk in full
rag-kit ask "..." --json                     # machine-readable
```

The answer is printed with its `[S1]`… markers followed by the sources, each
with file, page (PDFs only) and similarity score. If nothing is retrieved (or
nothing passes `--min-score`), the LLM is not called and the status is
`no_results`.

## Inspect retrieval

```bash
rag-kit search "What is a countable noun?" -k 8          # no LLM call
rag-kit search "..." --full                               # whole chunk text
rag-kit search "..." --json                               # scores + metadata
```

Each hit shows score, file, page, `chunk_id` and `doc_id`. With `--json`, step
progress goes to stderr and stdout holds only the JSON.

## Optional FastAPI service

```bash
pip install -e ".[api]"
rag-kit serve --port 8000            # or: uvicorn rag_kit.api:app --port 8000
rag-kit serve --collection experiments
```

`--collection` (also on `ui`) applies to that server process only; without it
the server uses `COLLECTION_NAME`. The command prints which collection it uses,
passes the project to the server in `RAG_PROJECT_DIR`, and never modifies
`.env`. When you start uvicorn yourself, run it inside the project or set
`RAG_PROJECT_DIR`.

- `GET /health` → `{"status": "ok", "ready": true}`
- `POST /query` with `{"question": "...", "top_k": 4}` →
  `{"answer": "...", "status": "answered" | "no_results", "sources": [{"page", "source", "score", "marker", "chunk_id", "text"}]}`

`answer` has the markers stripped; `marker` on each source maps them back.
Pipeline failures (including a missing project) return 503 with the reason.
Questions longer than 4000 characters are rejected with 422.

The service has no authentication and binds to `127.0.0.1` by default; do not
expose it publicly. To embed it elsewhere, build your own instance with
`rag_kit.api.create_app(settings=..., pipeline=...)`.

## Optional Streamlit test UI

```bash
pip install -e ".[ui]"
rag-kit ui                           # http://localhost:8501
```

Upload and ingest documents, ask questions or run retrieval only, and inspect
scores, pages, chunk text and metadata. Uploads are saved under the project's
`uploads/` folder (git-ignored here). It is a testing tool, not a production
front end.

## Use from Python

```python
from rag_kit import Pipeline, Settings

settings = Settings.load("path/to/project")    # reads path/to/project/.env
pipeline = Pipeline(settings=settings)
pipeline.ingest("data/book.pdf")
result = pipeline.ask("What is a noun?")
print(result.status, result.answer_without_markers)
for source in result.sources:
    print(source["marker"], source["file"], source["page"], source["score"])
pipeline.close()
```

`Settings.load()` without a folder finds the project the same way the CLI
does. Override values with `settings.replace(top_k=8)`. `Settings.load` does
not change `os.environ`, and API keys are left out of its `repr`.

The pipeline reports progress through the `rag_kit` logger and prints nothing
on its own; call `rag_kit.log.show_progress()` (as the CLI does) or configure
`logging` yourself to see it.

## Supported inputs and providers

- **Files:** `.pdf` (text layer required), `.txt` and `.md` (UTF-8).
- **Embeddings:** any sentence-transformers model through Hugging Face, or
  Gemini embeddings.
- **LLM:** Gemini via `langchain-google-genai`.
- **Vector store:** Qdrant, embedded (`QDRANT_PATH`) or server (`QDRANT_URL`).

### PDF font repair

Some PDFs embed subset fonts without a `ToUnicode` map, and every extractor
returns scrambled glyphs (`& ? ! & &`).
[`pdf_font_repair.py`](https://github.com/shamiulriyad/rag-learning/blob/main/src/rag_kit/pdf_font_repair.py) reverses that
substitution for the `-Free-English-Grammar.pdf` kept in this repository (it
is not part of any package). It is off by default; enable it with
`PDF_FONT_REPAIR=true` or `--font-repair on`. Its maps are specific to that
PDF; for other broken PDFs, use OCR instead.

## Tests

```bash
pip install -e ".[dev,gemini]"
python -m pytest                     # unit tests: no network, no model download, no API calls
```

The unit tests never read your `.env` or touch your Qdrant store. Integration
tests are opt-in. They run `rag-kit` against this checkout's real `.env` and
need the `local` extra:

```bash
# PowerShell: $env:RAG_RUN_INTEGRATION = "1"
RAG_RUN_INTEGRATION=1 python -m pytest -m integration
RAG_RUN_INTEGRATION=1 RAG_RUN_GEMINI=1 python -m pytest -m "integration or gemini"   # uses Gemini quota
```

They read `COLLECTION_NAME` without changing it, and ingest only into a
uniquely named collection inside a temporary Qdrant folder. Stop `serve` and
`ui` first.

## Troubleshooting

| Message | Fix |
| ------- | --- |
| `No rag-kit project found` | Run inside a folder with `rag-kit.toml`, pass `--project DIR`, or set `RAG_PROJECT_DIR`. |
| `[warn] .env  not created yet` (from `rag-kit check`) | Copy the template: `cp .env.example .env` (PowerShell: `Copy-Item .env.example .env`), then set `GOOGLE_API_KEY`. Without `.env`, rag-kit looks for a Qdrant server instead of a local store. |
| `No local Qdrant store at …` | Ingest something first, or point `QDRANT_PATH` at the existing store. |
| `… is in use by another process` | Embedded Qdrant allows one process. Stop `serve`/`ui`/other commands, or use a Qdrant server. |
| `Collection 'x' holds N-dimensional vectors, but … produces M` | The embedding model changed. Restore `EMBEDDING_MODEL`, use another `COLLECTION_NAME`, or `--recreate`. |
| `GOOGLE_API_KEY is not set` | Put the key in the project's `.env`. |
| `… is not installed. Run: pip install "rag-kit[…]"` | Install the extra named in the message. |
| `… could not answer … 429` | Gemini rate limit or quota. Wait, or raise `EMBED_SLEEP` when using Gemini embeddings. |
| `… page(s) look corrupted` | Scrambled text: try `--font-repair on`; scanned PDF: run OCR (e.g. `ocrmypdf`). |
| `Unsupported file type` | Convert to PDF, `.txt` or `.md`. |

## Known limitations

- Embedded Qdrant is single-process: run one of CLI / API / UI at a time.
- No OCR: scanned PDFs need to be OCR'd first.
- Documents are identified by file name within a collection.
- Only Gemini is wired up for generation.
- Chunks indexed before the metadata migration lack `doc_id` and `file_type`;
  re-ingest the file to add them.

## License

[MIT](https://github.com/shamiulriyad/rag-learning/blob/main/LICENSE)
