# {{PROJECT_NAME}}

A retrieval-augmented generation (RAG) project built on
[rag-kit](https://github.com/shamiulriyad/rag-learning) {{RAG_KIT_VERSION}}:
index your documents into a local Qdrant store, then ask questions and get
answers that cite the passages (and PDF pages) they came from.

Embeddings: **{{EMBEDDINGS_LABEL}}**. {{EMBEDDINGS_NOTE}}

## Set up

1. **Create `.env` from the template** (this project never contains a real key
   until you add one):

   ```bash
   cp .env.example .env              # PowerShell: Copy-Item .env.example .env
   ```

   Open `.env` and set `GOOGLE_API_KEY`
   ([get a key](https://aistudio.google.com/app/apikey)). Answers always need
   it. Never commit `.env`; it is already in `.gitignore`.

2. **Activate the virtual environment** created by rag-kit-dev:

   ```bash
   source .venv/bin/activate         # Windows PowerShell: .venv\Scripts\Activate.ps1
   ```

   No `.venv` yet (created with `--no-install`)? See "Install manually" below.

3. **Check the setup:**

   ```bash
   rag-kit check
   ```

## Use

```bash
rag-kit ingest data/your-document.pdf      # .pdf, .txt or .md; re-ingesting replaces
rag-kit ask "What does the document say about ...?"
rag-kit search "..."                        # retrieval only, no LLM call
rag-kit documents                           # what is indexed
python example.py data/your-document.pdf "Your question"   # the same from Python
```

Optional extras: `pip install "ragkit-dev[api]=={{RAG_KIT_VERSION}}"` for
`rag-kit serve` (HTTP API on 127.0.0.1), `pip install "ragkit-dev[ui]=={{RAG_KIT_VERSION}}"`
for `rag-kit ui` (Streamlit test UI).

## Files

| Path | Purpose |
| ---- | ------- |
| `rag-kit.toml` | marks this folder as a rag-kit project |
| `.env.example` | settings template; copy it to `.env` |
| `requirements.txt` | the rag-kit version and extras this project uses |
| `data/` | put your documents here |
| `example.py` | ingest and ask from Python |
| `qdrant_data/` | the local vector store, created on the first ingest (git-ignored) |

## Install manually

```bash
python3.11 -m venv .venv                    # Windows: py -3.11 -m venv .venv
{{MANUAL_TORCH_STEP}}.venv/bin/python -m pip install -r requirements.txt   # Windows: .venv\Scripts\python.exe -m pip ...
```

See the [rag-kit README](https://github.com/shamiulriyad/rag-learning#readme)
for all settings and troubleshooting.
