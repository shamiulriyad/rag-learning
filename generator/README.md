# rag-kit-dev

Create a [rag-kit](https://github.com/shamiulriyad/rag-learning) project with
one command: a folder with settings, a document folder and an example, plus a
`.venv` with rag-kit installed.

```bash
npx rag-kit-dev my-rag
```

You need **Node.js 20+** and **Python 3.11 or 3.12** (3.11 is preferred when
both are installed). [uv](https://docs.astral.sh/uv/) is used when it is
installed; otherwise pip.

## The embedding choice

You are asked how the project creates embeddings, with what each option costs,
before anything is installed. There is no default; in scripts and CI pass
`--embeddings`.

- **`local`** - BAAI/bge-m3 on your computer. No API key for embeddings.
  Installs PyTorch and sentence-transformers: about 1 GB on disk (measured on
  Windows); actual disk use varies by platform and dependency versions. On Linux
  the CPU-only PyTorch build is used unless you pass `--gpu`. The BGE-M3 model
  (about 2.3 GB) is downloaded separately into the Hugging Face cache the first
  time you ingest a document, never during setup.
- **`gemini`** - Google's embedding API. Small install, no model download.
  Needs a `GOOGLE_API_KEY` with embedding quota; document text is sent to
  Google.

Either way, answers are written by Gemini and need `GOOGLE_API_KEY`.

## What you get

```
my-rag/
  rag-kit.toml       marks the project folder
  .env.example       settings template - copy it to .env and add your key
  .gitignore         keeps .env, qdrant_data/ and .venv/ out of git
  requirements.txt   rag-kit[...]==<this generator's version>
  data/              put your documents here
  example.py         ingest and ask from Python
  README.md          next steps
  .venv/             unless --no-install
```

rag-kit-dev **never creates `.env` and never asks for an API key**. Copy
`.env.example` to `.env` (`cp .env.example .env`, or
`Copy-Item .env.example .env` in PowerShell) and add the key yourself.

## Options

```
--embeddings local|gemini   choose without being asked (required when not interactive)
--gpu                       local embeddings on Linux: keep PyTorch's CUDA build
--python PATH               use this Python 3.11/3.12 interpreter
--no-uv                     use pip even if uv is installed
--no-install                only write the project files
-y, --yes                   never prompt (needs --embeddings)
-h, --help / -v, --version
```

Testing only: `--package-spec SPEC` installs rag-kit from a local wheel or a
requirement such as `rag-kit==0.1.0rc1`; `--test-pypi` takes rag-kit (and only
rag-kit) from TestPyPI.

## Safety

- The project name must be a plain folder name; paths, `..`, and Windows
  device names are refused, and an existing folder must be empty. These checks,
  the embedding choice and finding Python all happen before any file is written.
- Existing files are never overwritten, and nothing is ever deleted. If the
  install fails, the project is kept and the exact commands to finish are printed.
- External programs are started without a shell, and environment values are
  never printed.

## License

MIT
