"""Release gates for .github/workflows/release.yml, kept out of shell so they can be tested.

    release_gate.py authorize --stage STAGE --tag TAG          # who may publish what
    release_gate.py manifest --dist DIR --npm DIR               # trusted build: expected hashes
    release_gate.py verify-artifacts --kind python|npm --dir DIR --version V
    release_gate.py check-index --index pypi|testpypi --version V [--wait S]
    release_gate.py check-npm --version V [--wait S]
    release_gate.py npm-preflight --version V                  # before anything is published
    release_gate.py check-environments --repo OWNER/REPO --environments a,b
    release_gate.py upload-plan --index pypi|testpypi --dir DIR --version V
    release_gate.py npm-publish-plan --version V                # just before npm publish

Registry uploads cannot be repeated (a version and a file name are used once), so
a re-run must not upload what the registry already has. upload-plan and
npm-publish-plan ask the registry first: files it already holds with exactly the
trusted build's hashes are skipped, anything else it holds for this version
(other bytes, unexpected or yanked files, an ambiguous file list) fails the job,
and only what is missing is published. Uploads are never retried blindly.

Manifests are read from environment variables (PYTHON_MANIFEST, NPM_MANIFEST),
never interpolated into shell. Outputs for $GITHUB_OUTPUT are written with
--github-output FILE as key=value lines. Every command exits 1 with the reasons
on any problem: the release fails closed.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from packaging.version import InvalidVersion, Version

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_versions import ROOT, check, npm_form  # noqa: E402

STAGES = ("rehearsal", "release")
INDEXES = {"pypi": "https://pypi.org", "testpypi": "https://test.pypi.org"}
NPM_REGISTRY = "https://registry.npmjs.org"
NPM_PACKAGE = "rag-kit-dev"
NPM_MAINTAINER = "shamiul"  # npm account that owns rag-kit-dev (RELEASING.md)
TAG_POLICY = {"name": "v*", "type": "tag"}


class GateError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


# --- authorize: stage, tag and version --------------------------------------------------


def parse_release_version(tag: str) -> Version:
    """The version a tag stands for. Only canonical tags are accepted: v + the PEP 440
    normal form with three release numbers, optionally aN/bN/rcN, nothing else."""
    if not tag.startswith("v"):
        raise GateError([f"tag {tag!r} must start with 'v'"])
    text = tag[1:]
    try:
        version = Version(text)
    except InvalidVersion:
        raise GateError([f"tag {tag!r} is not a version"]) from None
    problems = []
    if str(version) != text:
        problems.append(f"tag {tag!r} is not canonical; write it as 'v{version}'")
    if len(version.release) != 3:
        problems.append(f"tag {tag!r} needs exactly three release numbers (X.Y.Z)")
    if version.epoch or version.dev is not None or version.post is not None or version.local:
        problems.append(f"tag {tag!r}: epochs, .dev, .post and +local versions are not released")
    if problems:
        raise GateError(problems)
    return version


def authorize(stage: str, tag: str, root: Path = ROOT) -> dict:
    """Outputs for the release workflow. production is 'true' only for exactly
    stage=release with a final version; anything unexpected raises."""
    if stage not in STAGES:  # exact, case-sensitive: "Release" or " release" are refused
        raise GateError([f"stage must be exactly one of {', '.join(STAGES)}; got {stage!r}"])
    version = parse_release_version(tag)
    problems = []
    if stage == "rehearsal" and not version.is_prerelease:
        problems.append(
            f"stage=rehearsal needs a pre-release tag (e.g. v{version}rc1); "
            f"{tag} would use up the final version on TestPyPI"
        )
    if stage == "release" and version.is_prerelease:
        problems.append(
            f"stage=release needs a final version; {tag} is a pre-release (rehearse it instead)"
        )
    problems += check(root, tag)  # pyproject == package.json == tag, CHANGELOG section
    if problems:
        raise GateError(problems)
    return {
        "production": "true" if stage == "release" else "false",
        "version": str(version),
        "npm-version": npm_form(str(version)),
    }


# --- artifacts: the trusted build's manifest, checked before and after publishing ----------


def expected_names(kind: str, version: str) -> set:
    if kind == "python":
        return {f"ragkit_dev-{version}-py3-none-any.whl", f"ragkit_dev-{version}.tar.gz"}
    if kind == "npm":
        return {f"rag-kit-dev-{npm_form(version)}.tgz"}
    raise GateError([f"unknown artifact kind {kind!r}"])


def digests(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha512": base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "size": len(data),
    }


def build_manifest(directory: Path, kind: str, version: str) -> dict:
    """{"version", "kind", "files": {name: digests}}; the folder must hold exactly the
    expected files for that version."""
    present = {p.name for p in directory.iterdir() if p.is_file()}
    expected = expected_names(kind, version)
    if present != expected:
        raise GateError(
            [f"{directory}: expected exactly {sorted(expected)}, found {sorted(present)}"]
        )
    return {
        "version": version,
        "kind": kind,
        "files": {name: digests(directory / name) for name in sorted(expected)},
    }


def verify_artifacts(manifest: dict, directory: Path, kind: str, version: str) -> list:
    """The downloaded files must be exactly the manifest's, for the authorized version."""
    problems = []
    expected = expected_names(kind, version)
    if manifest.get("kind") != kind or manifest.get("version") != version:
        problems.append(
            f"manifest is for {manifest.get('kind')} {manifest.get('version')}, "
            f"expected {kind} {version}"
        )
    listed = set(manifest.get("files", {}))
    if listed != expected:
        problems.append(f"manifest lists {sorted(listed)}, expected {sorted(expected)}")
    present = {p.name for p in directory.iterdir() if p.is_file()} if directory.is_dir() else set()
    for name in sorted(expected - present):
        problems.append(f"missing artifact: {name}")
    for name in sorted(present - expected):
        problems.append(f"unexpected artifact: {name}")
    for name in sorted(expected & present & listed):
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual != manifest["files"][name]["sha256"]:
            problems.append(
                f"{name}: sha256 {actual} does not match the build's "
                f"{manifest['files'][name]['sha256']}"
            )
    return problems


INDEX_MISSING = "index is missing "  # the only problem that may still be propagating


def _index_files(release_json) -> tuple:
    """({file name: sha256}, problems) from PyPI's JSON API for one release. Anything
    that would make the file list ambiguous is a problem, never dropped or overwritten:
    an entry that is not an object or has no file name, a file listed twice, and a
    yanked file (a withdrawn release is never "already published")."""
    urls = release_json.get("urls") if isinstance(release_json, dict) else None
    if not isinstance(urls, list):
        return {}, ["the index answered without a file list; refusing to continue unverified"]
    files, problems = {}, []
    for entry in urls:
        if not isinstance(entry, dict):
            problems.append(f"the index lists a file entry that is not an object: {entry!r}")
            continue
        name = entry.get("filename")
        if not isinstance(name, str) or not name:
            problems.append(f"the index lists a file without a file name: {entry!r}")
            continue
        if name in files:
            problems.append(f"the index lists {name} more than once")
            continue
        if entry.get("yanked"):
            problems.append(f"the index reports {name} as yanked: this version was withdrawn, "
                            "release the next version")
        digests = entry.get("digests")
        if not isinstance(digests, dict):
            problems.append(f"the index lists {name} without a digests object: {digests!r}")
            digests = {}
        files[name] = digests.get("sha256")
    return files, problems


def compare_index(manifest: dict, release_json: dict) -> list:
    """PyPI's JSON API for one release vs the manifest: same files, same sha256,
    none of them yanked."""
    reported, problems = _index_files(release_json)
    expected = {name: d["sha256"] for name, d in manifest["files"].items()}
    problems += [f"{INDEX_MISSING}{name}" for name in sorted(set(expected) - set(reported))]
    problems += [
        f"index has an unexpected file {name}" for name in sorted(set(reported) - set(expected))
    ]
    problems += [
        f"{name}: index reports sha256 {reported[name]}, build has {expected[name]}"
        for name in sorted(set(expected) & set(reported))
        if reported[name] != expected[name]
    ]
    return problems


def compare_npm(manifest: dict, integrity: str) -> list:
    if len(manifest.get("files", {})) != 1:
        return [
            f"npm manifest must list exactly one tarball, lists {sorted(manifest.get('files', {}))}"
        ]
    [(name, d)] = manifest["files"].items()
    expected = f"sha512-{d['sha512']}"
    return (
        []
        if integrity.strip() == expected
        else [
            f"npm reports integrity {integrity.strip()!r} for the published package, the build's "
            f"{name} is {expected!r}"
        ]
    )


def npm_preflight(status: int, document, version: str) -> list:
    """What can be known about npm before anything is published: rag-kit-dev exists
    (trusted publishing cannot create a package; the one-time placeholder, RELEASING.md),
    its public metadata lists NPM_MAINTAINER as a maintainer, and it does not have this
    version yet (a version can never be published twice). It cannot see the trusted
    publisher configuration, so npm can still fail after PyPI for other reasons."""
    if status == 404:
        return [f"{NPM_PACKAGE} is not on npm yet: trusted publishing cannot create a package; "
                "publish the one-time placeholder first (RELEASING.md)"]
    if status != 200:
        return [f"cannot read {NPM_PACKAGE} from the npm registry (HTTP {status}); "
                "refusing to publish unverified"]
    document = document if isinstance(document, dict) else {}
    versions = document.get("versions")
    published = set(versions) if isinstance(versions, dict) else set()
    if not published:
        return [f"{NPM_PACKAGE} is on npm without any published version (unpublished?); "
                "trusted publishing cannot be configured for it"]
    listed = document.get("maintainers")
    maintainers = [m.get("name") for m in (listed if isinstance(listed, list) else [])
                   if isinstance(m, dict)]
    if NPM_MAINTAINER not in maintainers:
        return [f"{NPM_PACKAGE} on npm is not maintained by {NPM_MAINTAINER!r} "
                f"(maintainers: {maintainers}); refusing to publish to a package we do not own"]
    if npm_form(version) in published:
        return [f"{NPM_PACKAGE}@{npm_form(version)} is already on npm; "
                "a version can never be published twice"]
    if _unpublished(document, version):
        return [f"{NPM_PACKAGE}@{npm_form(version)} was published and then unpublished; "
                "npm never allows that version again: release the next version"]
    return []


def _unpublished(document: dict, version: str) -> bool:
    """True if npm's `time` map lists the version although `versions` does not. npm
    adds a version to `time` only when it is published, and the registry appears to
    keep that entry after an unpublish (observed behaviour, not documented by npm).
    Without the entry this check simply does not fire; npm then refuses the publish."""
    times = document.get("time")
    return isinstance(times, dict) and npm_form(version) in times


# --- resume: publish only what the registry does not already have ---------------------------


def python_upload_plan(manifest: dict, status: int, release_json) -> tuple:
    """(file names still to upload, problems) for one release on PyPI/TestPyPI, from its
    JSON API answer. 404: nothing is there yet, upload everything. 200: files with the
    build's sha256 are already published and are skipped; another sha256, a file the
    build does not have, a yanked file or an ambiguous file list means this version is
    not ours to complete."""
    expected = {name: d["sha256"] for name, d in manifest["files"].items()}
    if status == 404:
        return sorted(expected), []
    if status != 200:
        return [], [f"cannot read the release from the index (HTTP {status}); "
                    "refusing to upload unverified"]
    reported, problems = _index_files(release_json)
    if problems:
        return [], problems
    problems = [f"the index already has {name}, which this build did not produce"
                for name in sorted(set(reported) - set(expected))]
    problems += [f"the index already has {name} with sha256 {reported[name]}, this build's is "
                 f"{expected[name]}: this version was published from other files"
                 for name in sorted(set(reported) & set(expected))
                 if reported[name] != expected[name]]
    if problems:
        return [], problems
    return sorted(set(expected) - set(reported)), []


def npm_publish_plan(manifest: dict, status: int, document, version: str) -> tuple:
    """(publish needed?, problems), from the registry's document for rag-kit-dev."""
    spec = f"{NPM_PACKAGE}@{npm_form(version)}"
    if status != 200 or not isinstance(document, dict):
        return False, [f"cannot read {NPM_PACKAGE} from the npm registry (HTTP {status}); "
                       "refusing to publish unverified"]
    versions = document.get("versions")
    entry = versions.get(npm_form(version)) if isinstance(versions, dict) else None
    if entry is None:
        if _unpublished(document, version):
            return False, [f"{spec} was published and then unpublished; npm never allows it again"]
        return True, []
    integrity = ((entry if isinstance(entry, dict) else {}).get("dist") or {}).get("integrity")
    problems = compare_npm(manifest, integrity or "")
    if problems:
        return False, [f"{spec} is already on npm from other files: {problems[0]}"]
    return False, []


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to the same scheme and host. urllib would otherwise
    follow one anywhere, Authorization header included."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (new.scheme, new.hostname, new.port) != (old.scheme, old.hostname, old.port):
            raise GateError([f"{req.full_url} redirected to {newurl} (HTTP {code}), another "
                             "host or scheme; refusing to continue unverified"])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameOriginRedirects)


def fetch_json(url: str, token: str = None):
    """(status, parsed JSON or None) for an HTTP answer. No answer (network error,
    timeout), an answer that is not JSON or a redirect to another host raises
    GateError: callers fail closed."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with _OPENER.open(request, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:  # an answer with an error status
        return exc.code, None
    except (urllib.error.URLError, OSError) as exc:  # no answer: DNS, refused, timeout
        reason = getattr(exc, "reason", None) or exc
        raise GateError([f"cannot reach {url} ({type(exc).__name__}: {reason}); "
                         "refusing to continue unverified"]) from None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError([f"{url} answered HTTP {status} with a body that is not JSON "
                         f"({type(exc).__name__}); refusing to continue unverified"]) from None


def wait_for(probe, wait: float, interval: float = 20):
    """Calls probe() -> (done, problems) until done or the time is up."""
    deadline = time.monotonic() + wait
    while True:
        done, problems = probe()
        if done or time.monotonic() >= deadline:
            return problems
        time.sleep(interval)


# --- environments: protection must be configured, not assumed ---------------------------


def evaluate_environment(name: str, environment, policies) -> list:
    """environment / policies: GitHub API JSON for the environment and its deployment
    branch policies (None when the API returned 404)."""
    if environment is None:
        return [f"environment {name!r} does not exist (GitHub would create it unprotected)"]
    problems = []
    rules = environment.get("protection_rules") or []
    reviewers = [
        r
        for rule in rules
        if rule.get("type") == "required_reviewers"
        for r in rule.get("reviewers") or []
    ]
    if not reviewers:
        problems.append(f"environment {name!r} has no required reviewers")
    if environment.get("can_admins_bypass", True):
        problems.append(f"environment {name!r} lets administrators bypass its protection rules")
    policy = environment.get("deployment_branch_policy") or {}
    if not (policy.get("custom_branch_policies") and not policy.get("protected_branches")):
        problems.append(f"environment {name!r} must allow deployments only from selected tags")
    else:
        listed = [
            {"name": p.get("name"), "type": p.get("type", "branch")}
            for p in (policies or {}).get("branch_policies", [])
        ]
        if listed != [TAG_POLICY]:
            problems.append(
                f"environment {name!r} deployment policies are {listed}, expected "
                f"only {[TAG_POLICY]}"
            )
    return problems


def check_environments(repo: str, names: list, token: str) -> list:
    problems = []
    api = f"https://api.github.com/repos/{repo}/environments"
    for name in names:
        status, environment = fetch_json(f"{api}/{name}", token)
        if status == 404:
            problems += evaluate_environment(name, None, None)
            continue
        if status != 200:
            problems.append(
                f"cannot read environment {name!r} (HTTP {status}): give the job "
                "'actions: read' or check the token; refusing to publish unverified"
            )
            continue
        policies = None
        if (environment.get("deployment_branch_policy") or {}).get("custom_branch_policies"):
            status, policies = fetch_json(f"{api}/{name}/deployment-branch-policies", token)
            if status != 200:
                problems.append(f"cannot read deployment policies of {name!r} (HTTP {status})")
                continue
        problems += evaluate_environment(name, environment, policies)
    return problems


# --- command line -----------------------------------------------------------------------


def _write_outputs(path, values: dict) -> None:
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(lines)
    print(lines, end="")


def _manifest_from_env(variable: str) -> dict:
    raw = os.environ.get(variable)
    if not raw:
        raise GateError([f"${variable} is empty: the trusted build's manifest did not arrive"])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError([f"${variable} is not valid JSON: {exc}"]) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--github-output", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("authorize")
    p.add_argument("--stage", required=True)
    p.add_argument("--tag", required=True)

    p = sub.add_parser("manifest")
    p.add_argument("--dist", type=Path, required=True)
    p.add_argument("--npm", type=Path, required=True)

    p = sub.add_parser("verify-artifacts")
    p.add_argument("--kind", choices=["python", "npm"], required=True)
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--version", required=True)

    p = sub.add_parser("check-index")
    p.add_argument("--index", choices=sorted(INDEXES), required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--wait", type=float, default=0)

    p = sub.add_parser("check-npm")
    p.add_argument("--version", required=True)
    p.add_argument("--wait", type=float, default=0)

    p = sub.add_parser("npm-preflight")
    p.add_argument("--version", required=True)

    p = sub.add_parser("check-environments")
    p.add_argument("--repo", required=True)
    p.add_argument("--environments", required=True)

    p = sub.add_parser("upload-plan")
    p.add_argument("--index", choices=sorted(INDEXES), required=True)
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--version", required=True)

    p = sub.add_parser("npm-publish-plan")
    p.add_argument("--version", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "authorize":
            _write_outputs(args.github_output, authorize(args.stage, args.tag, args.root))
            return 0

        if args.command == "manifest":
            import tomllib

            version = tomllib.loads((args.root / "pyproject.toml").read_text(encoding="utf-8"))
            version = version["project"]["version"]
            python = build_manifest(args.dist, "python", version)
            npm = build_manifest(args.npm, "npm", version)
            _write_outputs(
                args.github_output,
                {
                    "python-manifest": json.dumps(python, separators=(",", ":"), sort_keys=True),
                    "npm-manifest": json.dumps(npm, separators=(",", ":"), sort_keys=True),
                },
            )
            return 0

        if args.command == "verify-artifacts":
            variable = "PYTHON_MANIFEST" if args.kind == "python" else "NPM_MANIFEST"
            problems = verify_artifacts(
                _manifest_from_env(variable), args.dir, args.kind, args.version
            )
            if problems:
                raise GateError(problems)
            print(f"{args.kind} artifacts are exactly the trusted build's ({args.version}).")
            return 0

        if args.command == "check-index":
            manifest = _manifest_from_env("PYTHON_MANIFEST")
            if manifest.get("version") != args.version:
                raise GateError([f"manifest is for {manifest.get('version')}, not {args.version}"])
            url = f"{INDEXES[args.index]}/pypi/ragkit-dev/{args.version}/json"

            def probe():
                status, release = fetch_json(url)
                if status != 200:
                    return False, [f"{url} answered HTTP {status}"]
                problems = compare_index(manifest, release)
                # A file still missing may just be propagating; anything else (a wrong
                # hash, an unexpected or yanked file, an ambiguous list) never is.
                propagating = problems and all(p.startswith(INDEX_MISSING) for p in problems)
                return not propagating, problems

            problems = wait_for(probe, args.wait)
            if problems:
                raise GateError(problems)
            print(f"{args.index} serves exactly the trusted build's files for {args.version}.")
            return 0

        if args.command == "check-npm":
            manifest = _manifest_from_env("NPM_MANIFEST")
            spec = f"rag-kit-dev@{npm_form(args.version)}"

            def probe():
                npm = shutil.which("npm")
                if not npm:
                    return True, ["npm is not on PATH"]
                result = subprocess.run(
                    [npm, "view", spec, "dist.integrity"], capture_output=True, text=True
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return False, [f"npm does not serve {spec} yet"]
                return True, compare_npm(manifest, result.stdout)

            problems = wait_for(probe, args.wait)
            if problems:
                raise GateError(problems)
            print(f"npm serves exactly the trusted build's tarball for {spec}.")
            return 0

        if args.command == "npm-preflight":
            status, document = fetch_json(f"{NPM_REGISTRY}/{NPM_PACKAGE}")
            problems = npm_preflight(status, document, args.version)
            if problems:
                raise GateError(problems)
            print(f"npm has {NPM_PACKAGE}, maintained by {NPM_MAINTAINER}, and not yet "
                  f"{NPM_PACKAGE}@{npm_form(args.version)}.")
            return 0

        if args.command == "check-environments":
            token = os.environ.get("GH_TOKEN", "")
            if not token:
                raise GateError(["GH_TOKEN is not set: cannot verify environment protection"])
            names = [n for n in args.environments.split(",") if n]
            problems = check_environments(args.repo, names, token)
            if problems:
                raise GateError(problems)
            print(
                f"environments {', '.join(names)}: required reviewers, no admin bypass, "
                f"deployments only from tags {TAG_POLICY['name']}."
            )
            return 0

        if args.command == "upload-plan":
            manifest = _manifest_from_env("PYTHON_MANIFEST")
            problems = verify_artifacts(manifest, args.dir, "python", args.version)
            if problems:
                raise GateError(problems)
            url = f"{INDEXES[args.index]}/pypi/ragkit-dev/{args.version}/json"
            status, release = fetch_json(url)
            upload, problems = python_upload_plan(manifest, status, release)
            if problems:
                raise GateError(problems)
            # The upload action publishes every file in the folder; drop the ones the
            # index already serves with exactly these bytes.
            for name in sorted(set(manifest["files"]) - set(upload)):
                (args.dir / name).unlink()
                print(f"{args.index} already has {name} with the build's sha256: "
                      "not uploaded again")
            for name in upload:
                print(f"to upload to {args.index}: {name}")
            _write_outputs(args.github_output, {"upload": "true" if upload else "false"})
            return 0

        if args.command == "npm-publish-plan":
            manifest = _manifest_from_env("NPM_MANIFEST")
            status, document = fetch_json(f"{NPM_REGISTRY}/{NPM_PACKAGE}")
            publish, problems = npm_publish_plan(manifest, status, document, args.version)
            if problems:
                raise GateError(problems)
            if not publish:
                print(f"npm already serves {NPM_PACKAGE}@{npm_form(args.version)} with the "
                      "build's integrity: not published again")
            _write_outputs(args.github_output, {"publish": "true" if publish else "false"})
            return 0
    except GateError as error:
        for problem in error.problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
