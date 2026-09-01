# PDF RAG - LangChain + Qdrant + Gemini

Every step in the pipeline is its own module, in order.

```
1  PDF                    ->  rag/step01_load_pdf.py
2  Text extraction        ->  rag/step02_extract_text.py
3  Text cleaning          ->  rag/step03_clean_text.py
4  Chunking               ->  rag/step04_chunking.py
5  Embedding              ->  rag/step05_embedding.py
6  Store in Qdrant        ->  rag/step06_vector_store.py
                              (steps 1-6 run from ingest.py)
7  User question          ->  rag/step07_user_question.py
8  Query embedding        ->  rag/step08_query_embedding.py
9  Retrieve chunks        ->  rag/step09_retrieve.py
10 Gemini                 ->  rag/step10_generate.py
11 Answer + sources       ->  rag/step11_answer.py
                              (steps 7-11 run from ask.py)
```

## Setup

```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then paste your Gemini API key
```

Start Qdrant (server mode):

```bash
docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

No Docker? Put `QDRANT_PATH=./qdrant_data` in `.env` and delete `QDRANT_URL`.
Qdrant then runs embedded, straight to disk.

## Run

```bash
python ingest.py --pdf data/your.pdf --recreate
python ask.py "what does chapter 3 say about X?"
python ask.py                                        # interactive
```

## Notes

- **Vector dimension is detected, not hard-coded.** `gemini-embedding-001`
  returns 3072 dims by default, and older tutorials assume 768. Step 5 embeds a
  probe string and creates the Qdrant collection with whatever size comes back.
- **Re-index after changing the embedding model.** Vectors from two different
  models are not comparable. Run with `--recreate`.
- **Scanned PDFs will not work.** Step 2 warns you if a page yields no text.
  Add OCR (pytesseract / ocrmypdf) before step 3 in that case.
- **Tuning retrieval.** `CHUNK_SIZE` 800-1200 suits prose; drop to 400-600 for
  dense tables and specs. Raise `TOP_K` if answers miss context, lower it if
  Gemini starts drifting off-topic.
- **Grounding.** Step 10 forbids outside knowledge and requires `[S1]` markers,
  so an answer without a marker is a red flag worth checking against the
  sources printed in step 11.
