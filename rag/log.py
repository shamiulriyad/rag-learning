"""Step progress goes through logging, not print().

Library code logs to the "rag" logger, which has only a NullHandler, so a
program that imports the pipeline sees no output unless it asks for it.
Applications (the CLI, the API service, the Streamlit UI) call
`show_progress()` to print the same "[1] Document : ..." lines as before.
"""

import logging
import sys

LOGGER_NAME = "rag"  # rag/__init__.py gives it a NullHandler


class _CurrentStdout(logging.StreamHandler):
    """Writes to whatever sys.stdout is when a record is emitted, so
    contextlib.redirect_stdout (the CLI's --json mode) and test capture still
    apply - exactly like the print() calls this replaces."""

    def __init__(self):
        super().__init__(sys.stdout)

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value):
        pass


def show_progress(level: int = logging.INFO) -> logging.Handler:
    """Print step progress (message text only) to stdout. Safe to call twice."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in [h for h in logger.handlers if isinstance(h, _CurrentStdout)]:
        logger.removeHandler(handler)
    handler = _CurrentStdout()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False  # do not print twice if the root logger is configured
    return handler
