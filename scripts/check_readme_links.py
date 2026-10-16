"""Check the links in the READMEs against the repository at a git ref.

    python scripts/check_readme_links.py                  # at HEAD
    python scripts/check_readme_links.py --ref v0.1.0     # at the release tag

README.md and generator/README.md are shown on PyPI and npm without the
repository, so every link in them must be absolute. Links into this
repository (github.com/.../tree|blob/main/..., raw.githubusercontent.com/.../main/...)
must name a folder (tree) or file (blob, raw) that exists at the ref. In other
Markdown files, relative links must resolve at the ref. External links are
not fetched here; a weekly workflow checks them.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REPO = "shamiulriyad/rag-learning"
# Shown on package indexes: links must be absolute.
INDEX_PAGES = ["README.md", "generator/README.md"]
OTHER_PAGES = ["generator/templates/default/README.md", "docs/pipeline.md", "CHANGELOG.md",
               "RELEASING.md"]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
REPO_LINK = re.compile(
    rf"https://(?:github\.com/{re.escape(REPO)}/(tree|blob)/main/|"
    rf"raw\.githubusercontent\.com/{re.escape(REPO)}/main/)([^#?]+)")


def object_type(ref: str, path: str, root: Path) -> str:
    result = subprocess.run(["git", "cat-file", "-t", f"{ref}:{path}"], cwd=root,
                            capture_output=True, text=True)
    return result.stdout.strip() or "missing"


def check_file(page: str, ref: str, root: Path, absolute_only: bool) -> list:
    problems = []
    text = (root / page).read_text(encoding="utf-8")
    for link in LINK.findall(text):
        if link.startswith(("http://", "https://", "mailto:")):
            match = REPO_LINK.match(link)
            if not match:
                continue  # external: checked weekly
            kind, path = match.group(1) or "raw", match.group(2).rstrip("/")
            expected = "tree" if kind == "tree" else "blob"
            actual = object_type(ref, path, root)
            if actual != expected:
                problems.append(f"{page}: {link} -> {path} is {actual} at {ref}, expected {expected}")
        elif link.startswith("#") or "{{" in link:
            continue  # same-page anchor, or a template placeholder
        elif absolute_only:
            problems.append(f"{page}: relative link {link!r} breaks on package index pages")
        else:
            target = str(PurePosixPath(page).parent / link.split("#")[0])
            normalized = str(PurePosixPath(*[p for p in PurePosixPath(target).parts if p != "."]))
            parts = []
            for part in PurePosixPath(normalized).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                else:
                    parts.append(part)
            if object_type(ref, "/".join(parts), root) == "missing":
                problems.append(f"{page}: relative link {link!r} does not resolve at {ref}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    problems, checked = [], 0
    for page, absolute_only in [(p, True) for p in INDEX_PAGES] + [(p, False) for p in OTHER_PAGES]:
        if not (args.root / page).exists():
            continue
        checked += 1
        problems += check_file(page, args.ref, args.root, absolute_only)
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{checked} files checked at {args.ref}: "
          + ("all repository links resolve." if not problems else f"{len(problems)} problem(s)."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
