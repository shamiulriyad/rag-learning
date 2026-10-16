"""STEP 8 - Query embedding.

The question is turned into a vector with the same model used in step 5.
LangChain's retriever would do this internally, but doing it explicitly keeps
the pipeline visible and lets you inspect or cache the vector.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def embed_question(embeddings, question: str) -> List[float]:
    vector = embeddings.embed_query(question)
    logger.info(f"[8] Query vec  : {len(vector)} dimensions")
    return vector
