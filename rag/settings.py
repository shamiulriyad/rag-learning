"""All tunable settings as one immutable object.

    settings = Settings.load(project_dir)          # project_dir/.env + environment
    pipeline = Pipeline(settings=settings)

`Settings.load` reads the project's `.env` without touching `os.environ`, and
real environment variables win over `.env`. Relative paths in it (`QDRANT_PATH`,
`PDF_PATH`) are resolved against the project directory - never against the
current working directory - so running a command from somewhere else cannot
silently point at a different, empty Qdrant store.

Every function that needs settings takes an optional `settings=`; without one
it uses `default_settings()`.
"""

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dotenv import dotenv_values

from rag.errors import ConfigError

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md")


def _resolve(project_dir: Path, value) -> Path:
    """Absolute paths stay as they are; relative ones are taken from project_dir."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (project_dir / path).resolve()


class _Reader:
    """Typed access to merged .env + environment values. Empty means unset."""

    def __init__(self, values: Mapping[str, Optional[str]]):
        self.values = values

    def text(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.values.get(name) or default

    def integer(self, name: str, default: str) -> int:
        raw = self.text(name, default)
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None

    def number(self, name: str, default: str) -> float:
        raw = self.text(name, default)
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"{name} must be a number, got {raw!r}.") from None

    def flag(self, name: str, default: str) -> bool:
        return self.text(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_dir: Path
    env_file: Path

    # --- Step 1-2: input document and extraction ----------------------------
    # Default file for `ingest` when no path is given on the command line.
    pdf_path: Path
    # Repairs PDFs whose subset fonts have no ToUnicode map (see
    # rag/pdf_font_repair.py). Off by default: ordinary PDFs do not need it.
    pdf_font_repair: bool = False

    # --- Step 4: chunking ---------------------------------------------------
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # --- Step 5: embedding --------------------------------------------------
    google_api_key: Optional[str] = field(default=None, repr=False)
    # "huggingface" runs a local model - no API key, no quota, no cost.
    # "google" uses Gemini embeddings (needs a real API key with embedding quota).
    embedding_provider: str = "huggingface"
    embedding_model: str = "BAAI/bge-m3"
    # None => detect the real dimension at runtime instead of hard-coding it.
    embedding_dim: Optional[int] = None
    embed_batch_size: int = 90
    # Gemini free tier allows ~100 embedded texts / minute; pause between batches
    # so a large PDF does not trip a 429. Not needed for a local model.
    embed_sleep: float = 0.0

    # --- Step 6: Qdrant -----------------------------------------------------
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = field(default=None, repr=False)
    # Local on-disk mode, no server. Takes priority over qdrant_url when set.
    qdrant_path: Optional[Path] = None
    collection_name: str = "pdf_rag"

    # --- Step 9: retrieval --------------------------------------------------
    top_k: int = 4
    # Chunks scoring below this are treated as "not relevant". None keeps every hit.
    min_score: Optional[float] = None

    # --- Step 10: Gemini LLM ------------------------------------------------
    llm_model: str = "gemini-2.5-flash"
    temperature: float = 0.2

    @classmethod
    def load(cls, project_dir, env_file=None,
             environ: Optional[Mapping[str, str]] = None) -> "Settings":
        """Read `env_file` (default: $RAG_ENV_FILE, else project_dir/.env) and
        overlay `environ` (default: os.environ). Neither is modified."""
        environ = os.environ if environ is None else environ
        project_dir = Path(project_dir).resolve()
        env_file = Path(env_file or environ.get("RAG_ENV_FILE") or (project_dir / ".env"))
        values = {**dotenv_values(env_file), **environ}  # environment wins, as before
        env = _Reader(values)

        provider = env.text("EMBEDDING_PROVIDER", "huggingface").lower()
        qdrant_path = env.text("QDRANT_PATH")
        min_score = env.text("MIN_SCORE")
        return cls(
            project_dir=project_dir,
            env_file=env_file,
            pdf_path=_resolve(project_dir, env.text("PDF_PATH", "data/sample.pdf")),
            pdf_font_repair=env.flag("PDF_FONT_REPAIR", "false"),
            chunk_size=env.integer("CHUNK_SIZE", "1000"),
            chunk_overlap=env.integer("CHUNK_OVERLAP", "150"),
            google_api_key=env.text("GOOGLE_API_KEY"),
            embedding_provider=provider,
            embedding_model=env.text("EMBEDDING_MODEL", "BAAI/bge-m3" if provider == "huggingface"
                                    else "models/gemini-embedding-001"),
            embedding_dim=env.integer("EMBEDDING_DIM", "0") or None,
            embed_batch_size=env.integer("EMBED_BATCH_SIZE", "90"),
            embed_sleep=env.number("EMBED_SLEEP", "60" if provider == "google" else "0"),
            qdrant_url=env.text("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=env.text("QDRANT_API_KEY"),
            qdrant_path=_resolve(project_dir, qdrant_path) if qdrant_path else None,
            collection_name=env.text("COLLECTION_NAME", "pdf_rag"),
            top_k=env.integer("TOP_K", "4"),
            min_score=env.number("MIN_SCORE", "0") if min_score else None,
            llm_model=env.text("LLM_MODEL", "gemini-2.5-flash"),
            temperature=env.number("TEMPERATURE", "0.2"),
        )

    def replace(self, **changes) -> "Settings":
        return dataclasses.replace(self, **changes)

    def resolve_path(self, value) -> Path:
        return _resolve(self.project_dir, value)

    def require_api_key(self) -> None:
        if not self.google_api_key:
            raise ConfigError(
                f"GOOGLE_API_KEY is not set. Copy .env.example to {self.env_file} and put your "
                "Gemini API key there (https://aistudio.google.com/app/apikey)."
            )

    def validate(self) -> None:
        """Fail early on settings that would only break halfway through a run."""
        if self.embedding_provider not in {"huggingface", "google"}:
            raise ConfigError(
                "EMBEDDING_PROVIDER must be 'huggingface' or 'google', "
                f"got {self.embedding_provider!r}."
            )
        if self.chunk_size <= 0 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ConfigError(
                f"Need CHUNK_SIZE > 0 and 0 <= CHUNK_OVERLAP < CHUNK_SIZE "
                f"(got {self.chunk_size} / {self.chunk_overlap})."
            )
        if self.top_k <= 0:
            raise ConfigError(f"TOP_K must be at least 1, got {self.top_k}.")
        if self.embedding_provider == "google":
            self.require_api_key()


_default: Optional[Settings] = None


def set_default_settings(settings: Settings) -> None:
    """Settings used by functions that are not given any."""
    global _default
    _default = settings


def default_settings() -> Settings:
    """The settings registered with set_default_settings().

    In this checkout, importing `config` registers the project's .env (and
    exports it to os.environ, as the toolkit always has). Packaging replaces
    this with project-directory discovery.
    """
    if _default is None:
        import config  # noqa: F401 - registers its settings on import
    return _default
