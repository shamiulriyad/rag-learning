"""Optional Streamlit UI for trying the pipeline - not a production app.

    pip install "ragkit-dev[ui]"
    rag-kit ui                             # http://localhost:8501

A chat with your documents. The question box stays at the bottom of the page,
every answer shows the chunks (and pages) it came from, and the sidebar library
adds and deletes documents. Uploads are saved under the project's uploads/
folder (git-ignored). Local Qdrant allows one process at a time, so stop
`serve` or other CLI commands while this runs. `rag-kit ui` passes the project
in RAG_PROJECT_DIR.
"""

import html
import re
import time
from pathlib import Path

import streamlit as st

from rag_kit.env import export_env_file
from rag_kit.errors import RagError
from rag_kit.log import show_progress
from rag_kit.pipeline import Pipeline
from rag_kit.settings import SUPPORTED_EXTENSIONS, default_settings
from rag_kit.step05_embedding import get_embeddings
from rag_kit.step06_vector_store import collection_exists, describe_location, get_client

st.set_page_config(page_title="rag-kit", page_icon=":material/menu_book:", layout="wide")
show_progress()  # step progress in the terminal running streamlit, as before
try:
    settings = default_settings()
except RagError as exc:  # no rag-kit project found
    st.error(str(exc))
    st.stop()
export_env_file(settings)  # HF_HOME, proxies etc. before the model loads
UPLOAD_DIR = settings.project_dir / "uploads"

ANSWER, SOURCES = "Answer with AI", "Sources only"
SUGGESTIONS = [
    "What topics does this document cover?",
    "What are the key terms and their definitions?",
    "Explain the most important idea with an example.",
]
_CITATION_RE = re.compile(r"[ \t]*\[S(\d+)\]")

# Colors are translucent so the same rules read well in light and dark themes.
STYLE = """
<style>
.block-container {padding-top: 2rem; max-width: 1100px;}
.rk-hero {padding: 1rem 1.3rem; border-radius: 16px; margin-bottom: .4rem;
  background: linear-gradient(135deg, rgba(99,102,241,.14), rgba(14,165,233,.08));
  border: 1px solid rgba(99,102,241,.26);}
.rk-row {display: flex; flex-wrap: wrap; align-items: baseline; gap: .4rem 1rem;}
.rk-title {font-size: 1.7rem; font-weight: 800; line-height: 1.1; letter-spacing: -.02em;
  background: linear-gradient(90deg, #6366f1, #0ea5e9); -webkit-background-clip: text;
  background-clip: text; color: transparent;}
.rk-sub {opacity: .75; font-size: .95rem;}
.rk-stats {display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .8rem;}
.rk-stat {padding: .35rem .75rem; border-radius: 10px;
  background: rgba(127,127,127,.09); border: 1px solid rgba(127,127,127,.20); font-size: .85rem;}
.rk-stat b {font-weight: 700; margin-right: .3rem;}
.rk-stat span {opacity: .7;}
.rk-empty {text-align: center; padding: 2rem 1rem 1rem; opacity: .85;}
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


def count_of(n: int, word: str) -> str:
    """'1 chunk', '620 chunks'."""
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def flash(state: str, text: str) -> None:
    """A message to show once, after the next rerun."""
    st.session_state.setdefault("flash", []).append((state, text))


# --- rendering helpers ---------------------------------------------------------------
def header(collection: str, docs: dict) -> None:
    stats = [
        (len(docs), "documents"),
        (f"{sum(docs.values()):,}", "chunks"),
        (collection, "collection"),
        (settings.llm_model, "answers"),
    ]
    tiles = "".join(f'<div class="rk-stat"><b>{html.escape(str(value))}</b>'
                    f"<span>{label}</span></div>" for value, label in stats)
    st.markdown(
        '<div class="rk-hero"><div class="rk-row"><div class="rk-title">rag-kit</div>'
        '<div class="rk-sub">Ask your documents. Every answer shows the pages it came from.'
        f'</div></div><div class="rk-stats">{tiles}</div></div>',
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
            with st.expander("Read the text"):
                st.text(chunk["text"])


def render_reply(msg: dict) -> None:
    kind = msg["kind"]
    if kind == "error":
        st.error(msg["text"], icon=":material/error:")
    elif kind == "empty":
        st.info(msg["text"], icon=":material/search_off:")
    elif kind == "answer":
        st.markdown(with_badges(msg["text"]))
    if msg["chunks"]:
        source_cards(msg["chunks"])
    if msg.get("footer"):
        st.caption(msg["footer"])


def render_message(msg: dict) -> None:
    if msg["role"] == "user":
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(msg["text"])
    else:
        with st.chat_message("assistant", avatar=":material/auto_stories:"):
            render_reply(msg)


def run_query(pipeline: Pipeline, question: str, mode: str, top_k: int, min_score: float) -> dict:
    reply = {"role": "assistant", "kind": "error", "text": "", "chunks": [], "footer": ""}
    started = time.perf_counter()
    try:
        if mode == ANSWER:
            result = pipeline.ask(question, k=top_k, min_score=min_score or None)
            reply.update(kind="answer" if result.status == "answered" else "empty",
                         text=result.answer, chunks=pack(result.scored_docs))
        else:
            scored = pipeline.search(question, k=top_k, min_score=min_score or None)
            reply.update(kind="sources" if scored else "empty", chunks=pack(scored),
                         text="No part of your documents matched. Lower the minimum relevance "
                              "or add a document.")
    except Exception as exc:  # noqa: BLE001 - shown in the UI
        reply["text"] = error_text(exc)
        return reply
    seconds = time.perf_counter() - started
    sources = count_of(len(reply["chunks"]), "source")
    if reply["kind"] == "answer":
        reply["footer"] = f"Answered from {sources} · {seconds:.1f} s"
    elif reply["kind"] == "sources":
        reply["footer"] = f"{sources} found, no AI call · {seconds:.1f} s"
    return reply


def queue_question(question: str) -> None:
    st.session_state["pending_question"] = question


@st.dialog("Add documents", width="large")
def add_documents(pipeline: Pipeline, collection: str) -> None:
    st.caption(f"Each file is split into chunks and stored in the **{collection}** collection. "
               "Adding a file with the same name again replaces the old version.")
    uploads = st.file_uploader("PDF, text or Markdown files",
                               type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
                               accept_multiple_files=True)
    font_repair = st.toggle("PDF font repair", value=settings.pdf_font_repair,
                            help="Leave this off. It only fixes one specific PDF whose text "
                                 "comes out as scrambled symbols.")
    st.caption("A long book can take several minutes on a laptop. Keep this window open.")
    if not st.button("Add to library", type="primary", icon=":material/upload:",
                     disabled=not uploads, width="stretch"):
        return
    UPLOAD_DIR.mkdir(exist_ok=True)
    for upload in uploads:
        path = UPLOAD_DIR / Path(upload.name).name
        path.write_bytes(upload.getbuffer())
        with st.status(f"Adding {path.name}...") as status:
            try:
                report = pipeline.ingest(path, font_repair=font_repair)
                flash("ok", f"Added **{path.name}**: {count_of(report['stored'], 'chunk')} "
                            f"from {count_of(report['pages'], 'page')}.")
                status.update(label=f"{path.name}: added", state="complete")
            except Exception as exc:  # noqa: BLE001 - shown in the UI
                flash("error", f"Could not add **{path.name}**: {error_text(exc)}")
                status.update(label=f"{path.name}: failed", state="error")
    st.rerun()  # closes the dialog and refreshes the library


# --- sidebar: settings (rendered first: everything else depends on the collection) ---
st.markdown(STYLE, unsafe_allow_html=True)
library = st.sidebar.container()
with st.sidebar:
    st.divider()
    st.markdown("### :material/tune: Settings")
    collection = st.text_input("Collection", value=settings.collection_name,
                               help="A separate library of documents. Each collection has "
                                    "its own files and chat.").strip()
    mode = st.segmented_control("Answer mode", [ANSWER, SOURCES], default=ANSWER, required=True,
                                help="Sources only shows the matching parts of your documents "
                                     "without calling the AI. It is free and instant.")
    top_k = st.slider("Sources per answer", 1, 20, settings.top_k,
                      help="How many chunks are read for each question. More gives broader "
                           "answers but takes longer.")
    min_score = st.slider("Minimum relevance", 0.0, 1.0, float(settings.min_score or 0.0), 0.05,
                          help="Ignore chunks less similar to the question than this. "
                               "0 keeps all of them.")
    if not settings.google_api_key:
        st.warning("GOOGLE_API_KEY is not set in .env. Sources only works; answers need the "
                   "key.", icon=":material/key_off:")
    st.divider()
    new_chat = st.button("New chat", icon=":material/add_comment:", width="stretch")
    st.caption(f"Embedding: {settings.embedding_model}  \nAnswers: {settings.llm_model}  \n"
               f"Store: {describe_location(settings)}")

if not collection:
    st.info("Enter a collection name in the sidebar to start.")
    st.stop()
pipeline = pipeline_for(collection)

docs, docs_error = {}, None
try:
    if collection_exists(shared_client(), collection, settings):  # a new project has none yet
        docs = pipeline.documents()
except RagError as exc:
    docs_error = str(exc)

chat_key = f"chat::{collection}"
if new_chat:
    st.session_state[chat_key] = []
history = st.session_state.setdefault(chat_key, [])

# --- sidebar: library -------------------------------------------------------------------
with library:
    st.markdown("### :material/library_books: Library")
    if st.button("Add documents", type="primary", icon=":material/upload_file:", width="stretch"):
        add_documents(pipeline, collection)
    if docs:
        for name, chunks in docs.items():
            text_col, delete_col = st.columns([5, 1], vertical_alignment="center")
            text_col.markdown(f"**{name}**  \n:gray[{count_of(chunks, 'chunk')}]")
            with delete_col.popover(":material/delete:", help=f"Delete {name}"):
                st.markdown(f"Delete **{name}** and its {count_of(chunks, 'chunk')} from this "
                            "collection?")
                if st.button("Delete", type="primary", key=f"delete::{collection}::{name}"):
                    try:
                        removed = pipeline.delete(name)
                        flash("ok", f"Deleted **{name}** ({count_of(removed, 'chunk')}).")
                    except Exception as exc:  # noqa: BLE001 - shown in the UI
                        flash("error", f"Could not delete **{name}**: {error_text(exc)}")
                    st.rerun()
    else:
        st.caption(docs_error or "No documents yet.")

# --- main: header, messages, chat ---------------------------------------------------------
header(collection, docs)
for state, text in st.session_state.pop("flash", []):
    if state == "ok":
        st.success(text, icon=":material/check_circle:")
    else:
        st.error(text, icon=":material/error:")

# In the main body (not in a tab or column) the question box is pinned to the bottom of
# the page, so it is always there for the next question.
question = st.chat_input("Ask a question about your documents" if docs else
                         "Add a document in the sidebar to start asking", disabled=not docs)
question = (question or st.session_state.pop("pending_question", None) or "").strip()

if not docs and not history:
    st.markdown('<div class="rk-empty"><b>Your library is empty</b>'
                "Add a PDF, text or Markdown file, then ask questions about it.</div>",
                unsafe_allow_html=True)
    _, middle, _ = st.columns([1, 1, 1])
    if middle.button("Add your first document", type="primary", icon=":material/upload_file:",
                     width="stretch"):
        add_documents(pipeline, collection)
elif not history and not question:
    st.markdown('<div class="rk-empty"><b>Ask your first question</b>'
                "Type it in the box at the bottom, or start with one of these. Answers cite "
                "their sources as S1, S2... with the page number.</div>",
                unsafe_allow_html=True)
    for column, suggestion in zip(st.columns(len(SUGGESTIONS)), SUGGESTIONS):
        column.button(suggestion, width="stretch", on_click=queue_question, args=(suggestion,))

for msg in history:
    render_message(msg)

if question:
    user_msg = {"role": "user", "text": question}
    history.append(user_msg)
    render_message(user_msg)
    with st.chat_message("assistant", avatar=":material/auto_stories:"):
        with st.spinner("Finding the matching sources..." if mode == SOURCES
                        else "Reading your documents and writing an answer..."):
            reply = run_query(pipeline, question, mode, top_k, min_score)
        render_reply(reply)
    history.append(reply)
