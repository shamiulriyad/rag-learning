"""STEP 11 - Answer + sources."""

import re
from typing import List, Tuple

from langchain_core.documents import Document

# Gemini tags claims with [S1], [S2]... (sometimes back-to-back).
_MARKER_RE = re.compile(r"[ \t]*(?:\[S\d+\])+")


def strip_markers(text: str) -> str:
    """Remove [S1]-style citation markers, e.g. for a UI that lists sources separately."""
    return _MARKER_RE.sub("", text).strip()


def build_sources(scored_docs: List[Tuple[Document, float]]) -> List[dict]:
    """One entry per retrieved chunk; `marker` matches the [S1].. tags in the answer."""
    return [
        {
            "marker": f"S{i}",
            "page": doc.metadata.get("page_number"),
            "file": doc.metadata.get("source_file"),
            "score": float(score),
            "chunk_id": doc.metadata.get("chunk_id"),
            "doc_id": doc.metadata.get("doc_id"),
            "text": doc.page_content,
        }
        for i, (doc, score) in enumerate(scored_docs, start=1)
    ]


def format_sources(scored_docs: List[Tuple[Document, float]], preview_chars: int = 160) -> str:
    lines = []
    for i, (doc, score) in enumerate(scored_docs, start=1):
        page = doc.metadata.get("page_number")
        source = doc.metadata.get("source_file", "document")
        where = f"{source}, page {page}" if page else source
        preview = " ".join(doc.page_content[:preview_chars].split())
        lines.append(f"  [S{i}] {where}  (score {score:.3f})\n       {preview}...")
    return "\n".join(lines)


def present(question: str, answer: str, scored_docs: List[Tuple[Document, float]]) -> dict:
    print("\n" + "=" * 72)
    print(f"Q: {question}")
    print("-" * 72)
    print(answer)
    print("-" * 72)
    print("Sources:" if scored_docs else "Sources: none (nothing relevant was retrieved)")
    if scored_docs:
        print(format_sources(scored_docs))
    print("=" * 72)

    return {
        "question": question,
        "answer": answer,
        "status": "answered" if scored_docs else "no_results",
        "sources": build_sources(scored_docs),
    }
