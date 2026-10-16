# Pipeline notes

Every step is its own module under `src/rag_kit/`, in order.
[`pipeline.py`](../src/rag_kit/pipeline.py) runs them; `rag-kit ingest` covers
steps 1–6 and `rag-kit ask` covers steps 7–11.

```
1  Input document         ->  step01_load_pdf.py      (.pdf, .txt, .md)
2  Text extraction        ->  step02_extract_text.py  (+ optional pdf_font_repair.py)
3  Text cleaning          ->  step03_clean_text.py
4  Chunking               ->  step04_chunking.py
5  Embedding              ->  step05_embedding.py
6  Store in Qdrant        ->  step06_vector_store.py
7  User question          ->  the CLI (cli.py), API (api.py) or UI (ui/app.py)
8  Query embedding        ->  step08_query_embedding.py
9  Retrieve chunks        ->  step09_retrieve.py
10 Gemini                 ->  step10_generate.py
11 Answer + sources       ->  step11_answer.py
```

Expected failures raise subclasses of `rag_kit.errors.RagError` whose messages
say how to fix the problem; the CLI, API and UI show them as-is.

Settings live in one immutable `rag_kit.settings.Settings` object. `Pipeline`
and every step take an optional `settings=`; without it they use
`rag_kit.settings.default_settings()`, which loads the project found from
`RAG_PROJECT_DIR` or the nearest `rag-kit.toml`. Loading settings never changes
`os.environ`; only the CLI, the default API app and the UI export an
allow-list of `.env` keys (see `rag_kit/env.py`).

Steps report progress with `logging` under the `rag_kit` logger rather than
printing. The CLI, API and UI turn it on with `rag_kit.log.show_progress()`;
under `--json` the CLI sends it to stderr so stdout holds only the JSON.

## Metadata

Each chunk carries `source_file`, `doc_id` (content hash), `file_type`, `page`
(0-based) and `page_number` (1-based; `None` for text files), `chunk_id` and
`start_index`. Step 11 cites `source_file` and `page_number`.

## Notes per step

- **Step 3: headers and footers.** A line that repeats on at least 60 % of the
  pages (4+ pages, under 80 characters) is treated as a header or footer and
  blanked where it appears as a whole line. The same words inside body text
  are kept.

- **Step 2: scanned PDFs do not work.** Extraction warns when a page yields no
  text. Add OCR (pytesseract / ocrmypdf) before step 3 in that case.
- **Step 2: broken font encodings.** Some PDFs embed subset fonts with no
  `ToUnicode` map, so every extractor returns scrambled glyphs (`& ? ! & &`).
  With `PDF_FONT_REPAIR=true`, extraction runs through `pdf_font_repair.py`,
  which reverses that substitution cipher for the bundled grammar PDF. Every
  page is then scored (`readable / corrupted / blank`). The maps are
  PDF-specific; OCR is the general fallback.
- **Step 4: tuning.** `CHUNK_SIZE` 800–1200 suits prose; drop to 400–600 for
  dense tables and specs.
- **Step 5: the vector dimension is detected, not hard-coded.**
  `BAAI/bge-m3` returns 1024 dimensions and `gemini-embedding-001` 3072. Step 6
  creates the collection with whatever size comes back and refuses to mix
  sizes later.
- **Step 6: re-index after changing the embedding model.** Vectors from two
  models are not comparable. Use a new `COLLECTION_NAME` or `--recreate`.
- **Step 6: re-ingesting replaces.** Point IDs are derived from file name,
  content hash and chunk position; stale chunks of the same file name are
  deleted after the new ones are stored.
- **Step 9: tuning.** Raise `TOP_K` if answers miss context, lower it if
  Gemini drifts off-topic. `MIN_SCORE` turns weak matches into an explicit
  "no results" instead of passing them to the LLM.
- **Step 10: grounding.** The prompt forbids outside knowledge and requires
  `[S1]` markers, so an answer without a marker is a red flag worth checking
  against the sources printed in step 11.
