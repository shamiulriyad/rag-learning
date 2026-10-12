"""STEP 10 - Gemini.

The retrieved chunks become the context. The prompt forces the model to answer
from that context only, and to tag every claim with the [S1]..[Sn] marker of
the chunk it came from - that is what makes step 11's sources trustworthy.
"""

from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

import config
from rag.errors import GenerationError

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


def get_llm() -> ChatGoogleGenerativeAI:
    config.require_api_key()
    return ChatGoogleGenerativeAI(
        model=config.LLM_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        temperature=config.TEMPERATURE,
    )


def format_context(scored_docs: List[Tuple[Document, float]]) -> str:
    blocks = []
    for i, (doc, _score) in enumerate(scored_docs, start=1):
        page = doc.metadata.get("page_number")
        source = doc.metadata.get("source_file", "document")
        where = f"{source}, page {page}" if page else source
        blocks.append(f"[S{i}] ({where})\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)


def generate_answer(question: str, scored_docs: List[Tuple[Document, float]], llm=None) -> str:
    if not scored_docs:
        return NO_RESULTS_ANSWER

    chain = PROMPT | (llm or get_llm()) | StrOutputParser()
    try:
        answer = chain.invoke({
            "context": format_context(scored_docs),
            "question": question,
        })
    except Exception as exc:
        raise GenerationError(
            f"{config.LLM_MODEL} could not answer: {exc}. Check GOOGLE_API_KEY, the "
            "LLM_MODEL name and your quota (HTTP 429 means rate-limited; wait and retry)."
        ) from exc

    print(f"[10] Gemini    : {config.LLM_MODEL} answered")
    return answer.strip()
