# Pipeline notes

Every step is its own module, in order. [`rag/pipeline.py`](../rag/pipeline.py)
runs them; `python cli.py ingest` covers steps 1–6 and `python cli.py ask`
covers steps 7–11.

```
1  Input document         ->  rag/step01_load_pdf.py      (.pdf, .txt, .md)
2  Text extraction        ->  rag/step02_extract_text.py  (+ optional rag/pdf_font_repair.py)
3  Text cleaning          ->  rag/step03_clean_text.py
4  Chunking               ->  rag/step04_chunking.py
5  Embedding              ->  rag/step05_embedding.py
6  Store in Qdrant        ->  rag/step06_vector_store.py
7  User question          ->  rag/step07_user_question.py
8  Query embedding        ->  rag/step08_query_embedding.py
9  Retrieve chunks        ->  rag/step09_retrieve.py
10 Gemini                 ->  rag/step10_generate.py
11 Answer + sources       ->  rag/step11_answer.py
```

Expected failures raise subclasses of `rag.errors.RagError` whose messages say
how to fix the problem; the CLI, API and UI show them as-is.

## Metadata

Each chunk carries `source_file`, `doc_id` (content hash), `file_type`, `page`
(0-based) and `page_number` (1-based; `None` for text files), `chunk_id` and
`start_index`. Step 11 cites `source_file` and `page_number`.

## Notes per step

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
