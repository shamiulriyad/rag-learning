"""Check that the installed rag-kit package is exactly what the wheel installed.

Run it with the Python of the environment to check:

    .venv/bin/python scripts/ci/check_wheel_install.py

Uses the installer's RECORD file (every installed file with its sha256):
  * each recorded file must still exist and match its hash, so a modified
    installed source is caught;
  * any other file inside the rag_kit/ package folder is unexpected - except
    Python's bytecode cache: __pycache__/<module>.<tag>.pyc for a module that
    exists. So importing the package (which writes .pyc files) is never a
    false positive, while data written into the package (a store, an upload,
    an edited file) always fails.
"""

import base64
import hashlib
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

DISTRIBUTION = "rag-kit"
PACKAGE = "rag_kit"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _is_bytecode_for_existing_module(path: Path) -> bool:
    if path.parent.name != "__pycache__" or path.suffix != ".pyc":
        return False
    module = path.name.split(".")[0]  # name.cpython-311.pyc / name.cpython-311.opt-1.pyc
    return (path.parent.parent / f"{module}.py").is_file()


def check() -> list:
    try:
        dist = distribution(DISTRIBUTION)
    except PackageNotFoundError:
        return [f"{DISTRIBUTION} is not installed in {sys.prefix}"]

    problems, recorded = [], set()
    package_dir = None
    for entry in dist.files or []:
        path = Path(entry.locate()).resolve()
        recorded.add(path)
        if entry.parts[0] == PACKAGE and package_dir is None:
            package_dir = path.parents[len(entry.parts) - 2]
        if entry.hash is None:
            continue  # RECORD itself, and bytecode some installers add without a hash
        if not path.is_file():
            problems.append(f"missing installed file: {entry}")
        elif _sha256(path) != entry.hash.value:
            problems.append(f"installed file was modified: {entry}")

    if package_dir is None:
        return problems + [f"RECORD lists no {PACKAGE}/ files"]
    for path in sorted(p.resolve() for p in package_dir.rglob("*") if p.is_file()):
        if path not in recorded and not _is_bytecode_for_existing_module(path):
            problems.append(
                f"unexpected file in the package: {path.relative_to(package_dir.parent)}"
            )
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(
            f"{DISTRIBUTION}: every installed file matches RECORD; no unexpected files "
            "(bytecode caches ignored)."
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
