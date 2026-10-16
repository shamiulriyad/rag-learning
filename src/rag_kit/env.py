"""Explicitly copy selected .env values into os.environ.

`Settings.load()` never touches os.environ. Some libraries, however, only read
their configuration from the environment - Hugging Face reads HF_HOME when it
is first imported, and HTTP clients read proxy variables - so a value placed
in the project's .env would otherwise be ignored.

`export_env_file(settings)` closes that gap with an allow-list. Only the
application entry points call it: the CLI, the default API app (`main.app`)
at startup, and the Streamlit UI. Importing the package, building a Pipeline
or calling create_app() never exports anything.

Policy:
  * Exported: variables other libraries read from the environment (see
    EXPORT_PREFIXES / EXPORT_NAMES), plus any names listed in RAG_EXPORT_ENV
    (comma-separated, in .env or the environment).
  * Never exported: rag-kit's own settings, including GOOGLE_API_KEY and
    QDRANT_API_KEY, and any RAG_* variable. Settings reads those directly, and
    server/UI child processes re-read .env themselves.
  * Variables already set in the process win; empty values are skipped.
  * Only names are ever logged or returned, never values. HF_TOKEN is a secret
    but is exported, because huggingface_hub reads it only from the environment.
"""

import logging
import os
from typing import List, MutableMapping, Optional

from dotenv import dotenv_values

from rag_kit.settings import SETTING_NAMES, Settings

logger = logging.getLogger(__name__)

OPT_IN_VARIABLE = "RAG_EXPORT_ENV"

# Hugging Face, transformers, sentence-transformers and torch runtime settings.
EXPORT_PREFIXES = ("HF_", "HUGGINGFACE_", "TRANSFORMERS_", "SENTENCE_TRANSFORMERS_", "TORCH_")
EXPORT_NAMES = frozenset({
    "TOKENIZERS_PARALLELISM", "CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
})
# Proxy variables are honoured in either case by most HTTP clients.
PROXY_NAMES = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"})


def is_rag_kit_setting(name: str) -> bool:
    return name in SETTING_NAMES or name.upper().startswith("RAG_")


def _allow_listed(name: str) -> bool:
    return (name in EXPORT_NAMES or name.upper() in PROXY_NAMES
            or name.startswith(EXPORT_PREFIXES))


def _opt_in_names(file_values: dict, environ: MutableMapping[str, str]) -> set:
    raw = environ.get(OPT_IN_VARIABLE) or file_values.get(OPT_IN_VARIABLE) or ""
    return {name.strip() for name in raw.split(",") if name.strip()}


def export_env_file(settings: Settings, environ: Optional[MutableMapping[str, str]] = None,
                    override: bool = False) -> List[str]:
    """Copy allow-listed and opted-in keys from settings.env_file into `environ`
    (default: os.environ). Returns the sorted names that were set."""
    environ = os.environ if environ is None else environ
    file_values = dotenv_values(settings.env_file)
    opt_in = _opt_in_names(file_values, environ)

    refused = sorted(name for name in opt_in if is_rag_kit_setting(name))
    if refused:
        logger.warning(f"    ! {OPT_IN_VARIABLE} lists rag-kit settings, which are never "
                       f"exported: {', '.join(refused)}")

    exported = []
    for name, value in file_values.items():
        if not value or is_rag_kit_setting(name):
            continue
        if not (_allow_listed(name) or name in opt_in):
            continue
        if name in environ and not override:
            continue  # the process environment wins
        environ[name] = value
        exported.append(name)
    return sorted(exported)
