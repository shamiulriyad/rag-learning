"""STEP 10 - Gemini.

The retrieved chunks become the context. The prompt forces the model to answer
from that context only, and to tag every claim with the [S1]..[Sn] marker of
the chunk it came from - that is what makes step 11's sources trustworthy.
"""

import logging
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from rag_kit.errors import GenerationError
from rag_kit.settings import Settings, default_settings

logger = logging.getLogger(__name__)

NO_RESULTS_ANSWER = "Nothing relevant was retrieved from the documents for this question."

SYSTEM_PROMPT = """You answer questions about a set of documents.

Rules:
- Use ONLY the context below. Do not add outside knowledge.
- After each claim, put the marker of the chunk it came from, like [S1] or [S2].
- If the context does not contain the answer, say exactly that the document does
  not cover it. Do not guess.
- Answer in the same language the question was asked in.
- Be direct. No preamble."""

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])


def get_llm(settings: Optional[Settings] = None) -> "ChatGoogleGenerativeAI":  # noqa: F821
    settings = settings or default_settings()
    settings.require_api_key()
    # Imported here so ingestion and retrieval work without the Gemini SDK.
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise GenerationError(
            f"Answer generation needs `pip install langchain-google-genai` ({exc})."
        ) from exc
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.temperature,
    )


def format_context(scored_docs: List[Tuple[Document, float]]) -> str:
    blocks = []
    for i, (doc, _score) in enumerate(scored_docs, start=1):
        page = doc.metadata.get("page_number")
        source = doc.metadata.get("source_file", "document")
        where = f"{source}, page {page}" if page else source
        blocks.append(f"[S{i}] ({where})\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)


def generate_answer(question: str, scored_docs: List[Tuple[Document, float]], llm=None,
                    settings: Optional[Settings] = None) -> str:
    if not scored_docs:
        return NO_RESULTS_ANSWER

    settings = settings or default_settings()
    chain = PROMPT | (llm or get_llm(settings)) | StrOutputParser()
    try:
        answer = chain.invoke({
            "context": format_context(scored_docs),
            "question": question,
        })
    except Exception as exc:
        raise GenerationError(
            f"{settings.llm_model} could not answer: {exc}. Check GOOGLE_API_KEY, the "
            "LLM_MODEL name and your quota (HTTP 429 means rate-limited; wait and retry)."
        ) from exc

    logger.info(f"[10] Gemini    : {settings.llm_model} answered")
    return answer.strip()
