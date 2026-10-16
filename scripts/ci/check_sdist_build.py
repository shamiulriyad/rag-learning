"""Check that the sdist builds the same package as the release wheel.

    python scripts/ci/check_sdist_build.py --sdist dist/rag_kit-X.tar.gz \
        --wheel dist/rag_kit-X-py3-none-any.whl

Builds a wheel from the sdist (uv build, isolated) and requires it to match
the release wheel: identical rag_kit/ files (by the sha256 in RECORD),
METADATA and entry points. A broken or incomplete sdist - one that cannot
build, or builds a different package - fails.
"""

import argparse
import csv
import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def wheel_contents(path: Path) -> dict:
    """{"files": {rag_kit/ path: sha256}, "METADATA": text, "entry_points.txt": text}."""
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        dist_info = next(n.split("/")[0] for n in names if n.endswith(".dist-info/RECORD"))
        record = csv.reader(io.StringIO(wheel.read(f"{dist_info}/RECORD").decode("utf-8")))
        files = {name: digest for name, digest, *_ in record if name.startswith("rag_kit/")}
        return {
            "files": files,
            "METADATA": wheel.read(f"{dist_info}/METADATA").decode("utf-8"),
            "entry_points.txt": wheel.read(f"{dist_info}/entry_points.txt").decode("utf-8"),
        }


def compare(release: dict, rebuilt: dict) -> list:
    problems = []
    for name in sorted(set(release["files"]) - set(rebuilt["files"])):
        problems.append(f"the sdist's wheel lacks {name}")
    for name in sorted(set(rebuilt["files"]) - set(release["files"])):
        problems.append(f"the sdist's wheel has an extra file {name}")
    for name in sorted(set(release["files"]) & set(rebuilt["files"])):
        if release["files"][name] != rebuilt["files"][name]:
            problems.append(f"{name} differs between the release wheel and the sdist's wheel")
    for part in ("METADATA", "entry_points.txt"):
        if release[part] != rebuilt[part]:
            problems.append(f"{part} differs between the release wheel and the sdist's wheel")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as out:
        result = subprocess.run(
            ["uv", "build", "--wheel", str(args.sdist), "--out-dir", out],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"FAIL the sdist does not build:\n{result.stdout}{result.stderr}")
            return 1
        rebuilt = next(Path(out).glob("*.whl"))
        problems = compare(wheel_contents(args.wheel), wheel_contents(rebuilt))
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(
            f"{args.sdist.name} builds a wheel identical to {args.wheel.name} "
            "(files, METADATA, entry points)."
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
