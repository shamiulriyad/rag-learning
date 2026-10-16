"""Optional Streamlit UI for testing the pipeline - not a production app.

    pip install "rag-kit[ui]"
    python cli.py ui                       # http://localhost:8501

Upload and ingest documents, ask questions, and inspect the retrieved chunks.
Uploads are saved under the project's uploads/ folder (git-ignored). Local
Qdrant allows one process at a time, so stop `serve` or other CLI commands
while this runs. `rag-kit ui` passes the project in RAG_PROJECT_DIR.
"""

from pathlib import Path

import streamlit as st

from rag_kit.env import export_env_file
from rag_kit.errors import RagError
from rag_kit.log import show_progress
from rag_kit.pipeline import Pipeline
from rag_kit.settings import SUPPORTED_EXTENSIONS, default_settings
from rag_kit.step05_embedding import get_embeddings
from rag_kit.step06_vector_store import describe_location, get_client

st.set_page_config(page_title="RAG toolkit - test UI", layout="wide")
show_progress()  # step progress in the terminal running streamlit, as before
try:
    settings = default_settings()
except RagError as exc:  # no rag-kit project found
    st.error(str(exc))
    st.stop()
export_env_file(settings)  # HF_HOME, proxies etc. before the model loads
UPLOAD_DIR = settings.project_dir / "uploads"


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


def show_error(exc: Exception) -> None:
    st.error(str(exc) if isinstance(exc, (RagError, ValueError)) else f"Unexpected error: {exc!r}")


# --- sidebar: settings + indexed documents -------------------------------------
with st.sidebar:
    st.header("Settings")
    collection = st.text_input("Collection", value=settings.collection_name).strip()
    top_k = st.slider("Chunks to retrieve (top k)", 1, 20, settings.top_k)
    min_score = st.number_input("Min score (0 = keep all)", 0.0, 1.0,
                                float(settings.min_score or 0.0), 0.05)
    st.caption(f"Store: {describe_location(settings)}")
    st.caption(f"Embedding: {settings.embedding_model}  \nLLM: {settings.llm_model}")
    if not settings.google_api_key:
        st.warning("GOOGLE_API_KEY is not set - retrieval works, answers will fail.")

    st.header("Indexed documents")
    try:
        docs = pipeline_for(collection).documents()
        if docs:
            st.dataframe([{"file": k, "chunks": v} for k, v in docs.items()],
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Collection is empty.")
    except RagError as exc:
        st.caption(str(exc))

if not collection:
    st.stop()
pipeline = pipeline_for(collection)

st.title("RAG toolkit - test UI")
tab_ask, tab_ingest = st.tabs(["Ask", "Ingest"])

# --- ingest -----------------------------------------------------------------------
with tab_ingest:
    uploads = st.file_uploader("Documents", type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
                               accept_multiple_files=True)
    font_repair = st.checkbox("PDF font repair", value=settings.pdf_font_repair,
                              help="Only for PDFs whose text extracts as scrambled glyphs.")
    st.caption(f"Re-ingesting a file with the same name replaces its chunks in '{collection}'.")
    if st.button("Ingest", disabled=not uploads, type="primary"):
        UPLOAD_DIR.mkdir(exist_ok=True)
        for upload in uploads:
            path = UPLOAD_DIR / Path(upload.name).name
            path.write_bytes(upload.getbuffer())
            with st.status(f"Ingesting {path.name}...") as status:
                try:
                    report = pipeline.ingest(path, font_repair=font_repair)
                    status.update(label=f"{path.name}: {report['stored']} chunks from "
                                        f"{report['pages']} page(s), collection now holds "
                                        f"{report['total']}", state="complete")
                    if report["removed_outdated"]:
                        st.caption(f"Removed {report['removed_outdated']} outdated chunks.")
                except Exception as exc:  # noqa: BLE001 - shown in the UI
                    status.update(label=f"{path.name}: failed", state="error")
                    show_error(exc)

# --- ask ----------------------------------------------------------------------------
with tab_ask:
    question = st.text_area("Question", placeholder="What does the document say about ...?")
    col_ask, col_search = st.columns([1, 1])
    run_ask = col_ask.button("Ask", type="primary", disabled=not question.strip())
    run_search = col_search.button("Retrieve only (no LLM)", disabled=not question.strip())

    if run_ask or run_search:
        try:
            with st.spinner("Working..."):
                if run_ask:
                    result = pipeline.ask(question, k=top_k, min_score=min_score or None)
                    scored = result.scored_docs
                else:
                    result = None
                    scored = pipeline.search(question, k=top_k, min_score=min_score or None)
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            show_error(exc)
            st.stop()

        if result is not None:
            st.subheader("Answer")
            if result.status == "no_results":
                st.info(result.answer)
            else:
                st.markdown(result.answer)

        st.subheader(f"Retrieved chunks ({len(scored)})")
        if not scored:
            st.info("No chunks were retrieved. Lower the min score or ingest a document.")
        st.dataframe([
            {"marker": f"S{i}", "score": round(score, 4), "file": d.metadata.get("source_file"),
             "page": d.metadata.get("page_number"), "chunk": d.metadata.get("chunk_id"),
             "chars": len(d.page_content)}
            for i, (d, score) in enumerate(scored, start=1)
        ], hide_index=True, use_container_width=True)
        for i, (doc, score) in enumerate(scored, start=1):
            page = doc.metadata.get("page_number")
            label = f"S{i} - {doc.metadata.get('source_file')}" + (f", page {page}" if page else "")
            with st.expander(f"{label} (score {score:.3f})"):
                st.text(doc.page_content)
                st.json(doc.metadata, expanded=False)
