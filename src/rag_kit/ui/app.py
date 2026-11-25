"""Optional Streamlit UI for trying the pipeline - not a production app.

    pip install "ragkit-dev[ui]"
    rag-kit ui                             # http://localhost:8501

Chat with your documents, see the chunks behind every answer, and add new
documents. Uploads are saved under the project's uploads/ folder (git-ignored).
Local Qdrant allows one process at a time, so stop `serve` or other CLI
commands while this runs. `rag-kit ui` passes the project in RAG_PROJECT_DIR.
"""

import html
import re
from pathlib import Path

import streamlit as st

from rag_kit.env import export_env_file
from rag_kit.errors import RagError
from rag_kit.log import show_progress
from rag_kit.pipeline import Pipeline
from rag_kit.settings import SUPPORTED_EXTENSIONS, default_settings
from rag_kit.step05_embedding import get_embeddings
from rag_kit.step06_vector_store import describe_location, get_client

st.set_page_config(page_title="rag-kit", page_icon=":material/menu_book:", layout="wide")
show_progress()  # step progress in the terminal running streamlit, as before
try:
    settings = default_settings()
except RagError as exc:  # no rag-kit project found
    st.error(str(exc))
    st.stop()
export_env_file(settings)  # HF_HOME, proxies etc. before the model loads
UPLOAD_DIR = settings.project_dir / "uploads"

ANSWER, RETRIEVE = "Answer", "Retrieve only"
SUGGESTIONS = [
    "What topics does this document cover?",
    "What are the key terms and their definitions?",
    "Explain the most important idea with an example.",
]
_CITATION_RE = re.compile(r"[ \t]*\[S(\d+)\]")

# Colors are translucent so the same rules read well in light and dark themes.
STYLE = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1150px;}
.rk-hero {padding: 1.4rem 1.6rem 1.2rem; border-radius: 18px; margin-bottom: .6rem;
  background: linear-gradient(135deg, rgba(99,102,241,.16), rgba(14,165,233,.10));
  border: 1px solid rgba(99,102,241,.28);}
.rk-title {font-size: 2.1rem; font-weight: 800; line-height: 1.15; letter-spacing: -.02em;
  background: linear-gradient(90deg, #6366f1, #0ea5e9); -webkit-background-clip: text;
  background-clip: text; color: transparent; width: fit-content;}
.rk-sub {margin-top: .3rem; opacity: .75; font-size: 1rem;}
.rk-stats {display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1rem;}
.rk-stat {padding: .55rem .9rem; border-radius: 12px; min-width: 105px;
  background: rgba(127,127,127,.09); border: 1px solid rgba(127,127,127,.20);}
.rk-stat b {display: block; font-size: 1.1rem; font-weight: 700; white-space: nowrap;}
.rk-stat span {font-size: .7rem; opacity: .65; text-transform: uppercase; letter-spacing: .06em;}
.rk-empty {text-align: center; padding: 2.2rem 1rem 1rem; opacity: .8;}
.rk-empty b {display: block; font-size: 1.15rem; margin-bottom: .3rem;}
</style>
"""


@st.cache_resource(show_spinner="Loading embedding model...")
def shared_embeddings():
    return get_embeddings(settings)


@st.cache_resource(show_spinner="Opening Qdrant...")
def shared_client():
    return get_client(create=True, settings=settings)


def pipeline_for(collection: str) -> Pipeline:
    # One client and one model for the whole app; a Pipeline per collection.
    cache = st.session_state.setdefault("pipelines", {})
    if collection not in cache:
        cache[collection] = Pipeline(collection=collection, embeddings=shared_embeddings(),
                                     client=shared_client(), settings=settings)
    return cache[collection]


def error_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, (RagError, ValueError)) else f"Unexpected error: {exc!r}"


# --- rendering helpers ---------------------------------------------------------------
def hero(collection: str, docs: dict) -> None:
    stats = [
        (len(docs), "documents"),
        (f"{sum(docs.values()):,}", "chunks"),
        (collection, "collection"),
        (settings.embedding_model.split("/")[-1], "embedding"),
        (settings.llm_model, "answer model"),
    ]
    tiles = "".join(f'<div class="rk-stat"><b>{html.escape(str(value))}</b>'
                    f"<span>{label}</span></div>" for value, label in stats)
    st.markdown(
        '<div class="rk-hero"><div class="rk-title">rag-kit</div>'
        '<div class="rk-sub">Ask your documents anything. Every answer shows the pages it '
        f'came from.</div><div class="rk-stats">{tiles}</div></div>',
        unsafe_allow_html=True,
    )


def pack(scored) -> list:
    """Plain dicts, so chat history survives reruns without holding Document objects."""
    return [{"text": doc.page_content, "meta": dict(doc.metadata), "score": float(score)}
            for doc, score in scored]


def with_badges(answer: str) -> str:
    return _CITATION_RE.sub(r" :blue-badge[S\1]", answer)


def source_cards(chunks: list) -> None:
    columns = st.columns(min(len(chunks), 3))
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk["meta"]
        page = meta.get("page_number")
        details = [f"page {page}" if page else None,
                   f"chunk {meta['chunk_id']}" if meta.get("chunk_id") is not None else None,
                   f"{len(chunk['text']):,} chars"]
        with columns[(i - 1) % len(columns)].container(border=True):
            st.markdown(f":blue-badge[S{i}] **{meta.get('source_file', 'unknown file')}**")
            st.caption(" · ".join(d for d in details if d))
            st.progress(min(max(chunk["score"], 0.0), 1.0),
                        text=f"relevance {chunk['score']:.3f}")
            with st.expander("Read chunk"):
                st.text(chunk["text"])


def render_reply(msg: dict) -> None:
    kind = msg["kind"]
    if kind == "error":
        st.error(msg["text"], icon=":material/error:")
    elif kind == "empty":
        st.info(msg["text"], icon=":material/search_off:")
    elif kind == "answer":
        st.markdown(with_badges(msg["text"]))
    else:  # retrieve only
        st.markdown(f":gray[{msg['text']}]")
    if msg["chunks"]:
        if kind == "answer":
            st.markdown(":gray[**Sources**]")
        source_cards(msg["chunks"])


def render_message(msg: dict) -> None:
    if msg["role"] == "user":
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(msg["text"])
    else:
        with st.chat_message("assistant", avatar=":material/auto_stories:"):
            render_reply(msg)


def run_query(pipeline: Pipeline, question: str, mode: str, top_k: int, min_score: float) -> dict:
    reply = {"role": "assistant", "kind": "error", "text": "", "chunks": []}
    try:
        if mode == ANSWER:
            result = pipeline.ask(question, k=top_k, min_score=min_score or None)
            reply.update(kind="answer" if result.status == "answered" else "empty",
                         text=result.answer, chunks=pack(result.scored_docs))
        else:
            scored = pipeline.search(question, k=top_k, min_score=min_score or None)
            reply.update(kind="retrieve" if scored else "empty", chunks=pack(scored),
                         text=f"{len(scored)} matching chunks, no LLM call." if scored else
                         "No chunks matched. Lower the minimum score or add a document.")
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        reply["text"] = error_text(exc)
    return reply


def queue_question(question: str) -> None:
    st.session_state["pending_question"] = question


# --- sidebar: settings ----------------------------------------------------------------
st.markdown(STYLE, unsafe_allow_html=True)
with st.sidebar:
    st.markdown("### :material/tune: Settings")
    collection = st.text_input("Collection", value=settings.collection_name,
                               help="The Qdrant collection to ask and add documents to.").strip()
    mode = st.segmented_control("Mode", [ANSWER, RETRIEVE], default=ANSWER, required=True,
                                help="Retrieve only shows the matching chunks without "
                                     "calling the LLM.")
    top_k = st.slider("Chunks per question", 1, 20, settings.top_k)
    min_score = st.slider("Minimum score", 0.0, 1.0, float(settings.min_score or 0.0), 0.05,
                          help="Drop chunks below this similarity. 0 keeps all of them.")
    if not settings.google_api_key:
        st.warning("GOOGLE_API_KEY is not set. Retrieval works, answers will fail.",
                   icon=":material/key_off:")

if not collection:
    st.info("Enter a collection name in the sidebar to start.")
    st.stop()
pipeline = pipeline_for(collection)

try:
    docs, docs_error = pipeline.documents(), None
except RagError as exc:
    docs, docs_error = {}, str(exc)

chat_key = f"chat::{collection}"
history = st.session_state.setdefault(chat_key, [])

# --- sidebar: library -----------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.markdown("### :material/library_books: Library")
    if docs:
        for name, chunks in sorted(docs.items()):
            st.markdown(f":material/description: **{name}**  \n:gray[{chunks:,} chunks]")
    else:
        st.caption(docs_error or "No documents yet. Add one in the Add documents tab.")
    st.divider()
    # Never disabled: the sidebar renders before this run's question is added.
    if st.button("Clear chat", icon=":material/delete_sweep:", width="stretch"):
        st.session_state[chat_key] = []
        st.rerun()
    st.caption(f"Store: {describe_location(settings)}")

hero(collection, docs)
tab_chat, tab_add = st.tabs([":material/forum: Chat", ":material/upload_file: Add documents"])

# --- chat -------------------------------------------------------------------------------
with tab_chat:
    feed = st.container()
    empty_state = feed.empty()
    if not history:
        with empty_state.container():
            st.markdown('<div class="rk-empty"><b>Ask your first question</b>'
                        "Answers cite their sources as S1, S2... with the page number."
                        "</div>", unsafe_allow_html=True)
            columns = st.columns(len(SUGGESTIONS))
            for column, suggestion in zip(columns, SUGGESTIONS):
                column.button(suggestion, width="stretch", on_click=queue_question,
                              args=(suggestion,), disabled=not docs)
    with feed:
        for msg in history:
            render_message(msg)

    question = st.chat_input("Ask about your documents...", disabled=not docs)
    question = (question or st.session_state.pop("pending_question", None) or "").strip()
    if question:
        empty_state.empty()
        user_msg = {"role": "user", "text": question}
        history.append(user_msg)
        with feed:
            render_message(user_msg)
            with st.chat_message("assistant", avatar=":material/auto_stories:"):
                with st.spinner("Reading the documents..." if mode == RETRIEVE
                                else "Reading the documents and writing an answer..."):
                    reply = run_query(pipeline, question, mode, top_k, min_score)
                render_reply(reply)
        history.append(reply)

# --- add documents ----------------------------------------------------------------------
with tab_add:
    left, right = st.columns([3, 2], gap="large")
    with left:
        uploads = st.file_uploader("Drop PDF, text or Markdown files",
                                   type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
                                   accept_multiple_files=True)
        start = st.button("Ingest", type="primary", icon=":material/rocket_launch:",
                          disabled=not uploads)
    with right, st.container(border=True):
        st.markdown("**What happens on ingest**")
        st.markdown("1. Text is extracted page by page and cleaned\n"
                    "2. It is split into overlapping chunks\n"
                    f"3. Each chunk is embedded and stored in :blue-badge[{collection}]")
        font_repair = st.toggle("PDF font repair", value=settings.pdf_font_repair,
                                help="Only for PDFs whose text extracts as scrambled glyphs.")
        st.caption("Re-ingesting a file with the same name replaces its chunks.")

    if start:
        UPLOAD_DIR.mkdir(exist_ok=True)
        reports = []
        for upload in uploads:
            path = UPLOAD_DIR / Path(upload.name).name
            path.write_bytes(upload.getbuffer())
            with st.status(f"Ingesting {path.name}...") as status:
                try:
                    report = pipeline.ingest(path, font_repair=font_repair)
                    reports.append(("ok", f"**{path.name}**: {report['stored']} chunks from "
                                          f"{report['pages']} page(s); the collection now "
                                          f"holds {report['total']:,}"
                                    + (f" ({report['removed_outdated']} outdated chunks "
                                       "removed)" if report["removed_outdated"] else "")))
                    status.update(label=f"{path.name}: done", state="complete")
                except Exception as exc:  # noqa: BLE001 - shown in the UI
                    reports.append(("error", f"**{path.name}**: {error_text(exc)}"))
                    status.update(label=f"{path.name}: failed", state="error")
        st.session_state["ingest_reports"] = reports
        st.rerun()  # refresh the library and stats with the new documents

    for state, text in st.session_state.get("ingest_reports", []):
        if state == "ok":
            st.success(text, icon=":material/check_circle:")
        else:
            st.error(text, icon=":material/error:")
