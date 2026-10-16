"""Check the contents of built rag-kit distributions before anyone installs them.

Build from a clean checkout or export of a commit, not from a working tree
with uncommitted files (CI checkouts are clean):

    git archive --format=tar HEAD | tar -x -C <export>      # an empty folder
    uv build <export> --out-dir <dir>                       # or python -m build
    python scripts/check_dist.py <dir>

Fails (exit 1) if a wheel or sdist contains anything outside the allow-list,
any user data (PDFs, .env files, Qdrant stores, uploads, data/), bytecode, or
if required files and metadata are missing. Prints what it checked.
"""

import re
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

EXTRAS = {"local", "gemini", "api", "ui", "dev", "all"}
ENTRY_POINT = "rag-kit = rag_kit.cli:main"

# Never allowed anywhere in an archive.
FORBIDDEN = [
    (re.compile(r"\.pdf$", re.I), "PDF"),
    (re.compile(r"(^|/)\.env$|(^|/)[^/]+\.env$"), ".env file"),
    (re.compile(r"(^|/)qdrant_data[^/]*(/|$)"), "Qdrant data"),
    (re.compile(r"(^|/)uploads(/|$)"), "uploads"),
    (re.compile(r"(^|/)data(/|$)"), "data folder"),
    (re.compile(r"(^|/)__pycache__(/|$)|\.py[cod]$"), "bytecode"),
    (re.compile(r"(^|/)\.git(/|$)|(^|/)\.venv(/|$)"), "repository/venv files"),
    (re.compile(r"(^|/)fix\d*\.txt$|(^|/)(work|portfolio|linkdin)\.txt$"), "personal notes"),
    # Hatchling force-adds .gitignore to sdists; hatch_build.py removes it.
    (re.compile(r"(^|/)\.gitignore$"), "VCS ignore file"),
]

# Everything an sdist may contain besides src/rag_kit/ and tests/.
SDIST_FILES = {"PKG-INFO", "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md",
               "hatch_build.py"}


def forbidden(names):
    return [f"{name}  ({why})" for name in names for pattern, why in FORBIDDEN
            if pattern.search(name)]


def check_wheel(path: Path, errors: list) -> None:
    with zipfile.ZipFile(path) as wheel:
        names = [n for n in wheel.namelist() if not n.endswith("/")]
        dist_info = next(n.split("/")[0] for n in names if ".dist-info/" in n)
        metadata = Parser().parsestr(wheel.read(f"{dist_info}/METADATA").decode())
        entry_points = wheel.read(f"{dist_info}/entry_points.txt").decode()

    outside = [n for n in names if not (n.startswith("rag_kit/") or n.startswith(dist_info + "/"))]
    errors += [f"{path.name}: outside the allow-list: {n}" for n in outside]
    errors += [f"{path.name}: {item}" for item in forbidden(names)]
    for required in ("rag_kit/__init__.py", "rag_kit/__main__.py", "rag_kit/cli.py",
                     "rag_kit/api.py", "rag_kit/ui/app.py", "rag_kit/py.typed"):
        if required not in names:
            errors.append(f"{path.name}: missing {required}")
    if not any(n.startswith(f"{dist_info}/licenses/") and n.endswith("LICENSE") for n in names):
        errors.append(f"{path.name}: LICENSE not included")
    if ENTRY_POINT not in entry_points.replace("  ", " "):
        errors.append(f"{path.name}: console script '{ENTRY_POINT}' missing")
    _check_metadata(path.name, metadata, errors)
    print(f"wheel  {path.name}: {len(names)} files "
          f"({sum(n.startswith('rag_kit/') for n in names)} in rag_kit/)")


def check_sdist(path: Path, errors: list) -> None:
    with tarfile.open(path) as sdist:
        names = [m.name for m in sdist.getmembers() if m.isfile()]
        root = PurePosixPath(names[0]).parts[0]
        metadata = Parser().parsestr(sdist.extractfile(f"{root}/PKG-INFO").read().decode())

    relative = [str(PurePosixPath(*PurePosixPath(n).parts[1:])) for n in names]
    outside = [n for n in relative
               if n not in SDIST_FILES and not n.startswith(("src/rag_kit/", "tests/"))]
    errors += [f"{path.name}: outside the allow-list: {n}" for n in outside]
    errors += [f"{path.name}: {item}" for item in forbidden(relative)]
    for required in ("pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", "hatch_build.py",
                     "src/rag_kit/__init__.py", "src/rag_kit/ui/app.py",
                     "tests/conftest.py", "tests/fixtures/empty_env.txt"):
        if required not in relative:
            errors.append(f"{path.name}: missing {required}")
    _check_metadata(path.name, metadata, errors)
    print(f"sdist  {path.name}: {len(names)} files "
          f"({sum(n.startswith('tests/') for n in relative)} in tests/)")


def _check_metadata(label: str, metadata, errors: list) -> None:
    expected = {"Name": "ragkit-dev", "Requires-Python": "<3.13,>=3.11",
                "License-Expression": "MIT"}
    for field, value in expected.items():
        if metadata.get(field) != value:
            errors.append(f"{label}: {field} is {metadata.get(field)!r}, expected {value!r}")
    extras = set(metadata.get_all("Provides-Extra") or [])
    if extras != EXTRAS:
        errors.append(f"{label}: extras {sorted(extras)}, expected {sorted(EXTRAS)}")
    if metadata.get("Author-email"):
        errors.append(f"{label}: unexpected Author-email in metadata")


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    wheels = sorted(folder.glob("ragkit_dev-*.whl"))
    sdists = sorted(folder.glob("ragkit_dev-*.tar.gz"))
    errors = []
    if len(wheels) != 1 or len(sdists) != 1:
        errors.append(f"expected one wheel and one sdist in {folder}, found "
                      f"{[p.name for p in wheels + sdists]}")
    for wheel in wheels:
        check_wheel(wheel, errors)
    for sdist in sdists:
        check_sdist(sdist, errors)
    for error in errors:
        print(f"FAIL {error}")
    print("All distribution checks passed." if not errors else f"{len(errors)} problem(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
