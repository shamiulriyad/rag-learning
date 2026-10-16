# Changelog

## 0.1.0 (unreleased)

First packaged release: the toolkit is now the installable Python package
`rag-kit` (import name `rag_kit`) with a `rag-kit` command.

### Migrating from the script-based checkout

Install the checkout as a package first (`pip install -e ".[local,gemini]"`,
plus `api`, `ui` or `dev` as needed; see the README).

| Before | Now |
| ------ | --- |
| `pip install -r requirements.txt` | `pip install -e ".[local,gemini]"` |
| `pip install -r requirements-api.txt` / `-ui.txt` / `-dev.txt` | extras `api`, `ui`, `dev` |
| `python cli.py <command> …` | `rag-kit <command> …` or `python -m rag_kit <command> …` |
| `python ingest.py FILE` | `rag-kit ingest FILE` |
| `python ingest.py --pdf FILE` | `rag-kit ingest FILE` (`--pdf` was removed) |
| `python ask.py "question"` | `rag-kit ask "question"` |
| `uvicorn main:app` | `rag-kit serve`, or `uvicorn rag_kit.api:app` |
| `streamlit run streamlit_app.py` | `rag-kit ui` |
| `python scripts/smoke_bge_m3.py` | `rag-kit check --deep` |
| `from rag.pipeline import Pipeline` | `from rag_kit import Pipeline` (or `rag_kit.pipeline`) |
| `from rag.<module> import …` | `from rag_kit.<module> import …` (same module names) |
| `import config; config.TOP_K` | `from rag_kit import Settings; Settings.load().top_k` |
| `main.create_app(...)` | `rag_kit.api.create_app(...)` |
| logger `rag` | logger `rag_kit` |
| `rag.step07_user_question` | removed (unused; the CLI and API take the question) |

### Changed behaviour

- **Project folder.** Commands work on the project given by `--project DIR`,
  else `RAG_PROJECT_DIR`, else the nearest folder at or above the current
  directory that contains `rag-kit.toml`. Without one they stop with an error.
  Previously paths were tied to the folder `cli.py` lived in, so commands
  worked from anywhere; now run them inside the project or pass `--project`.
  This repository contains a `rag-kit.toml`, so its `.env` and `qdrant_data/`
  keep working.
- **Environment export.** Importing `config` used to copy every `.env` key,
  including `GOOGLE_API_KEY`, into `os.environ`. Now only the `rag-kit`
  command, the default API app and the UI export, and only an allow-list
  (Hugging Face / PyTorch runtime variables, proxies, CA bundles, plus names
  in `RAG_EXPORT_ENV`). rag-kit's own settings are never exported. See
  "Variables for other libraries" in the README.
- **`rag-kit serve` / `ui`** always pass the project to the server process in
  `RAG_PROJECT_DIR`; `--collection` still applies to that process only.
- **`rag-kit check`** reads dependencies from the installed package's extras
  and names the extra to install (`pip install "rag-kit[api]"`). It also
  prints the project folder and the names of exported variables, and explains
  how to create `.env` from `.env.example` when it is missing.
- **UI uploads** go to the project's `uploads/` folder.
- **API** returns 503 when no project can be found.

### Unchanged

Collection defaults (`pdf_rag`, `BAAI/bge-m3`), the chunk ID namespace and
metadata keys, the `[S1]` source markers, the `/health`, `/query` and
`documents --json` schemas, and the 4000-character question limit. Existing
Qdrant collections need no migration.

### Earlier fixes in this release

- Header/footer removal no longer deletes matching words from body text.
- The Gemini SDK is imported only when an answer is generated.
- Settings are an injectable, side-effect-free `Settings` object.
- Library code logs instead of printing; `--json` keeps stdout pure.
- API application factory (`create_app`) with a race-free pipeline and a
  4000-character question limit.
