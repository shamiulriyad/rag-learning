"""STEP 9 - Retrieve relevant chunks.

Cosine similarity search in Qdrant against the query vector from step 8.
Returns (Document, score) pairs, highest score first. With a `min_score`
(MIN_SCORE in .env), weaker hits are dropped, and an empty result means
"nothing relevant" rather than "the k least-bad chunks".
"""

from typing import List, Optional, Tuple

from langchain_core.documents import Document


def retrieve(vector_store, query_vector: List[float], k: int,
             min_score: Optional[float] = None) -> List[Tuple[Document, float]]:
    results = vector_store.similarity_search_with_score_by_vector(query_vector, k=k)

    dropped = 0
    if min_score is not None:
        kept = [(doc, score) for doc, score in results if score >= min_score]
        dropped = len(results) - len(kept)
        results = kept

    note = f" ({dropped} below min score {min_score})" if dropped else ""
    print(f"[9] Retrieved  : {len(results)} chunks{note}")
    for i, (doc, score) in enumerate(results, start=1):
        page = doc.metadata.get("page_number") or "-"
        preview = doc.page_content[:70].replace("\n", " ")
        print(f"    S{i} page {page} | score {score:.3f} | {preview}...")

    return results
