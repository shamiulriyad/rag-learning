"""Check that the installed rag-kit package is exactly what the wheel installed.

Run it with the Python of the environment to check:

    uv pip install --link-mode copy --python .venv/bin/python <wheel>
    .venv/bin/python scripts/ci/check_wheel_install.py

Install with --link-mode copy: uv's default hardlinks installed files to its
cache, so they would not be this environment's own files (and writing to one
would change the cache and every other environment linked to it).

With --wheel PATH it also proves where rag-kit came from: every installed
rag_kit/ file must have the hash recorded in that wheel's RECORD. Installers do
not record the index they used, so this is how a release rehearsal shows the
installed package is the build that was uploaded (to TestPyPI), not another
build with the same version from somewhere else.

Uses the installer's RECORD file (every installed file with its sha256):
  * each recorded file must still exist and match its hash, so a modified
    installed source is caught;
  * any other file inside the rag_kit/ package folder is unexpected - except
    Python's bytecode cache: __pycache__/<module>.<tag>.pyc for a module that
    exists. So importing the package (which writes .pyc files) is never a
    false positive, while data written into the package (a store, an upload,
    an edited file) always fails.
"""

import argparse
import base64
import csv
import hashlib
import io
import sys
import zipfile
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


def wheel_hashes(wheel: Path) -> dict:
    """{path in the wheel: sha256} for the rag_kit/ files listed in its RECORD."""
    with zipfile.ZipFile(wheel) as archive:
        record = next(n for n in archive.namelist() if n.endswith(".dist-info/RECORD"))
        rows = csv.reader(io.StringIO(archive.read(record).decode("utf-8")))
        return {
            name: digest.removeprefix("sha256=")
            for name, digest, *_ in rows
            if name.startswith(f"{PACKAGE}/") and digest
        }


def check_against_wheel(wheel: Path) -> list:
    expected = wheel_hashes(wheel)
    installed = {
        str(entry).replace("\\", "/"): entry.hash.value
        for entry in distribution(DISTRIBUTION).files or []
        if entry.parts[0] == PACKAGE and entry.hash is not None
    }
    problems = [f"{name}: not installed" for name in sorted(set(expected) - set(installed))]
    problems += [
        f"{name}: installed but not in {wheel.name}"
        for name in sorted(set(installed) - set(expected))
    ]
    problems += [
        f"{name}: differs from {wheel.name}"
        for name in sorted(set(expected) & set(installed))
        if expected[name] != installed[name]
    ]
    return problems


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path, help="the wheel rag-kit must have come from")
    args = parser.parse_args(argv)

    problems = check()
    if not problems and args.wheel:
        problems = check_against_wheel(args.wheel)
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(
            f"{DISTRIBUTION}: every installed file matches RECORD; no unexpected files "
            "(bytecode caches ignored)."
            + (f" Installed files are exactly those of {args.wheel.name}." if args.wheel else "")
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
