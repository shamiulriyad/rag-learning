"""Keep the Python package and the npm generator on the same version.

    python scripts/check_versions.py                 # pyproject == package.json == CHANGELOG
    python scripts/check_versions.py --tag v0.1.0    # ... and the release tag
    python scripts/check_versions.py --set 0.1.1     # bump pyproject and package.json together

The generator installs ragkit-dev==<its own version>, so the two must always
match. They are compared as PEP 440 versions: npm writes a release candidate
as 0.1.0-rc.1, Python as 0.1.0rc1, and pip treats both the same.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
PROJECT_VERSION = re.compile(r'^(\[project\][^\[]*?^version\s*=\s*")([^"]+)(")', re.M | re.S)


def read_versions(root: Path) -> dict:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((root / "generator" / "package.json").read_text(encoding="utf-8"))
    return {"pyproject.toml": pyproject["project"]["version"],
            "generator/package.json": package["version"]}


def npm_form(version: str) -> str:
    """0.1.0rc1 -> 0.1.0-rc.1 (npm semver); final releases are unchanged."""
    v = Version(version)
    base = ".".join(str(part) for part in v.release)
    if v.pre:
        label = {"a": "alpha", "b": "beta", "rc": "rc"}[v.pre[0]]
        return f"{base}-{label}.{v.pre[1]}"
    if v.is_devrelease or v.is_postrelease or v.local:
        raise ValueError(f"{version}: dev, post and local versions are not released")
    return base


def check(root: Path, tag: str = None) -> list:
    problems = []
    versions = read_versions(root)
    try:
        parsed = {name: Version(value) for name, value in versions.items()}
    except InvalidVersion as exc:
        return [f"not a valid version: {exc}"]
    if len(set(parsed.values())) != 1:
        problems.append("versions differ: " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    version = parsed["pyproject.toml"]
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(rf"^## {re.escape(str(version))}\b(.*)$", changelog, re.M)
    if not heading:
        problems.append(f"CHANGELOG.md has no '## {version}' section")
    elif tag is not None and not version.is_prerelease and "unreleased" in heading[1].lower():
        # A final release is permanent; its notes must not ship saying "unreleased".
        problems.append(f"CHANGELOG.md still marks {version} as unreleased; "
                        "replace that with the release date before tagging")
    if tag is not None:
        if not tag.startswith("v"):
            problems.append(f"tag {tag!r} must look like v{version}")
        else:
            try:
                if Version(tag[1:]) != version:
                    problems.append(f"tag {tag} does not match version {version}")
            except InvalidVersion:
                problems.append(f"tag {tag!r} is not a version")
    return problems


def set_version(root: Path, version: str) -> None:
    Version(version)  # validate
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new_text, count = PROJECT_VERSION.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise SystemExit("could not find version in [project] of pyproject.toml")
    pyproject.write_text(new_text, encoding="utf-8")

    package_path = root / "generator" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = npm_form(version)
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="release tag that must match, e.g. v0.1.0")
    parser.add_argument("--set", metavar="VERSION",
                        help="write VERSION to both files (PEP 440 form)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.set:
        set_version(args.root, args.set)
        print(f"set pyproject.toml to {args.set} and generator/package.json to "
              f"{npm_form(args.set)}")
    versions = read_versions(args.root)
    problems = check(args.root, args.tag)
    summary = ", ".join(f"{k}: {v}" for k, v in versions.items())
    print(summary + (f", tag: {args.tag}" if args.tag else ""))
    for problem in problems:
        print(f"FAIL {problem}")
    print("Versions are in sync." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
