"""scripts/release_gate.py: release authorization, artifact integrity, environment checks."""

import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from tests.conftest import ROOT

SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "release_gate.py").exists(), reason="release scripts are not part of the sdist"
)

if (SCRIPTS / "release_gate.py").exists():
    sys.path.insert(0, str(SCRIPTS))
    import release_gate as gate
    from check_versions import set_version


def _project(tmp_path, version):
    """A copy of the version-bearing files, set to `version` with a CHANGELOG section."""
    (tmp_path / "generator").mkdir()
    for rel in ("pyproject.toml", "generator/package.json"):
        shutil.copy(ROOT / rel, tmp_path / rel)
    set_version(tmp_path, version)
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version}\n", encoding="utf-8")
    return tmp_path


def _problems(call):
    with pytest.raises(gate.GateError) as caught:
        call()
    return " | ".join(caught.value.problems)


# --- R1, R4, R5: stage authorization and canonical tags ------------------------------------


def test_release_of_a_final_version_is_production(tmp_path):
    root = _project(tmp_path, "0.1.0")
    assert gate.authorize("release", "v0.1.0", root) == {
        "production": "true",
        "version": "0.1.0",
        "npm-version": "0.1.0",
    }


def test_rehearsal_of_a_prerelease_is_never_production(tmp_path):
    root = _project(tmp_path, "0.1.0rc1")
    assert gate.authorize("rehearsal", "v0.1.0rc1", root) == {
        "production": "false",
        "version": "0.1.0rc1",
        "npm-version": "0.1.0-rc.1",
    }


@pytest.mark.parametrize(
    "stage",
    [
        "Release",
        "RELEASE",
        " release",
        "release ",
        "release\n",
        "Rehearsal",
        "prod",
        "publish",
        "",
        "true",
        "release,rehearsal",
    ],
)
def test_any_other_stage_value_is_refused(tmp_path, stage):
    root = _project(tmp_path, "0.1.0")
    assert "stage must be exactly one of rehearsal, release" in _problems(
        lambda: gate.authorize(stage, "v0.1.0", root)
    )


def test_rehearsal_refuses_a_final_version(tmp_path):
    root = _project(tmp_path, "0.1.0")
    assert "stage=rehearsal needs a pre-release tag" in _problems(
        lambda: gate.authorize("rehearsal", "v0.1.0", root)
    )


@pytest.mark.parametrize("version", ["0.1.0rc1", "0.1.0a2", "0.1.0b1"])
def test_release_refuses_a_prerelease(tmp_path, version):
    root = _project(tmp_path, version)
    assert "stage=release needs a final version" in _problems(
        lambda: gate.authorize("release", f"v{version}", root)
    )


@pytest.mark.parametrize(
    "tag, message",
    [
        ("0.1.0", "must start with 'v'"),
        ("V0.1.0", "must start with 'v'"),
        ("vnext", "is not a version"),
        ("v", "is not a version"),
        ("v0.1.0-rc.1", "is not canonical; write it as 'v0.1.0rc1'"),
        ("v0.1.0RC1", "is not canonical"),
        ("v0.1.0.rc1", "is not canonical"),
        ("v0.1.0-1", "is not canonical"),
        ("v00.1.0", "is not canonical"),
        ("v0.1", "exactly three release numbers"),
        ("v0.1.0.0", "exactly three release numbers"),
        ("v0.1.0.dev1", ".dev, .post and +local"),
        ("v0.1.0.post1", ".dev, .post and +local"),
        ("v0.1.0+local", ".dev, .post and +local"),
        ("v1!0.1.0", "epochs"),
    ],
)
def test_noncanonical_or_malformed_tags_are_refused(tag, message):
    assert message in _problems(lambda: gate.parse_release_version(tag))


def test_tag_must_match_the_package_versions(tmp_path):
    root = _project(tmp_path, "0.1.0")
    assert "does not match version 0.1.0" in _problems(
        lambda: gate.authorize("release", "v0.2.0", root)
    )


def test_versions_must_agree_and_have_a_changelog_entry(tmp_path):
    root = _project(tmp_path, "0.1.0")
    package = json.loads((root / "generator/package.json").read_text(encoding="utf-8"))
    package["version"] = "0.1.1"
    (root / "generator/package.json").write_text(json.dumps(package), encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    problems = _problems(lambda: gate.authorize("release", "v0.1.0", root))
    assert "versions differ" in problems and "CHANGELOG.md has no" in problems


def test_a_final_release_refuses_changelog_notes_marked_unreleased(tmp_path):
    root = _project(tmp_path, "0.1.0")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0 (unreleased)\n", encoding="utf-8")
    assert "still marks 0.1.0 as unreleased" in _problems(
        lambda: gate.authorize("release", "v0.1.0", root))
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0 (2026-11-02)\n", encoding="utf-8")
    assert gate.authorize("release", "v0.1.0", root)["production"] == "true"


def test_unreleased_notes_are_fine_before_tagging_and_for_release_candidates(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _project(candidate, "0.1.0rc1")
    (candidate / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0rc1 (unreleased)\n",
                                            encoding="utf-8")
    assert gate.authorize("rehearsal", "v0.1.0rc1", candidate)["production"] == "false"
    final = tmp_path / "final"
    final.mkdir()
    _project(final, "0.1.0")
    (final / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0 (unreleased)\n", encoding="utf-8")
    assert gate.check(final) == []  # CI on every commit; only the tag check refuses it


def test_authorize_cli_writes_outputs_only_on_success(tmp_path):
    root = _project(tmp_path, "0.1.0")
    out = tmp_path / "github_output"
    ok = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "release_gate.py"),
            "--root",
            str(root),
            "--github-output",
            str(out),
            "authorize",
            "--stage",
            "release",
            "--tag",
            "v0.1.0",
        ],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert out.read_text(encoding="utf-8") == "production=true\nversion=0.1.0\nnpm-version=0.1.0\n"

    out.unlink()
    bad = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "release_gate.py"),
            "--root",
            str(root),
            "--github-output",
            str(out),
            "authorize",
            "--stage",
            "Release",
            "--tag",
            "v0.1.0",
        ],
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1 and "FAIL stage must be exactly" in bad.stderr
    assert not out.exists()  # no production=true (or anything) on failure


# --- R2: manifest, pre-publish verification, post-publish comparison ------------------------


def _artifacts(tmp_path, version="0.1.0"):
    dist, npm = tmp_path / "dist", tmp_path / "npm"
    dist.mkdir()
    npm.mkdir()
    (dist / f"ragkit_dev-{version}-py3-none-any.whl").write_bytes(b"wheel bytes")
    (dist / f"ragkit_dev-{version}.tar.gz").write_bytes(b"sdist bytes")
    (npm / f"rag-kit-dev-{gate.npm_form(version)}.tgz").write_bytes(b"npm tarball bytes")
    return dist, npm


def test_manifest_records_sha256_and_npm_integrity(tmp_path):
    dist, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert (
        manifest["files"]["ragkit_dev-0.1.0.tar.gz"]["sha256"]
        == hashlib.sha256(b"sdist bytes").hexdigest()
    )
    npm_manifest = gate.build_manifest(npm, "npm", "0.1.0")
    assert (
        gate.compare_npm(
            npm_manifest, "sha512-" + npm_manifest["files"]["rag-kit-dev-0.1.0.tgz"]["sha512"]
        )
        == []
    )


@pytest.mark.parametrize("extra, missing", [("stray.whl", None), (None, "ragkit_dev-0.1.0.tar.gz")])
def test_manifest_refuses_an_unexpected_file_list(tmp_path, extra, missing):
    dist, _ = _artifacts(tmp_path)
    if extra:
        (dist / extra).write_bytes(b"x")
    if missing:
        (dist / missing).unlink()
    assert "expected exactly" in _problems(lambda: gate.build_manifest(dist, "python", "0.1.0"))


def test_verified_artifacts_pass(tmp_path):
    dist, npm = _artifacts(tmp_path)
    assert (
        gate.verify_artifacts(gate.build_manifest(dist, "python", "0.1.0"), dist, "python", "0.1.0")
        == []
    )
    assert (
        gate.verify_artifacts(gate.build_manifest(npm, "npm", "0.1.0"), npm, "npm", "0.1.0") == []
    )


def test_a_changed_artifact_is_refused(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    (dist / "ragkit_dev-0.1.0-py3-none-any.whl").write_bytes(b"tampered")
    assert any(
        "sha256" in p and "does not match the build's" in p
        for p in gate.verify_artifacts(manifest, dist, "python", "0.1.0")
    )


def test_missing_and_extra_artifacts_are_refused(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    (dist / "ragkit_dev-0.1.0.tar.gz").unlink()
    (dist / "ragkit_dev-9.9.9-py3-none-any.whl").write_bytes(b"other")
    problems = gate.verify_artifacts(manifest, dist, "python", "0.1.0")
    assert "missing artifact: ragkit_dev-0.1.0.tar.gz" in problems
    assert "unexpected artifact: ragkit_dev-9.9.9-py3-none-any.whl" in problems


def test_a_manifest_for_another_version_is_refused(tmp_path):
    dist, _ = _artifacts(tmp_path, "0.1.0")
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    problems = gate.verify_artifacts(manifest, dist, "python", "0.1.1")
    assert any("manifest is for python 0.1.0, expected python 0.1.1" in p for p in problems)
    assert "missing artifact: ragkit_dev-0.1.1.tar.gz" in problems


def test_verify_cli_reads_the_manifest_from_the_environment(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = json.dumps(gate.build_manifest(dist, "python", "0.1.0"))
    run = lambda env: subprocess.run(  # noqa: E731
        [
            sys.executable,
            str(SCRIPTS / "release_gate.py"),
            "verify-artifacts",
            "--kind",
            "python",
            "--dir",
            str(dist),
            "--version",
            "0.1.0",
        ],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **env},
    )
    assert run({"PYTHON_MANIFEST": manifest}).returncode == 0
    empty = run({"PYTHON_MANIFEST": ""})
    assert empty.returncode == 1 and "manifest did not arrive" in empty.stderr
    broken = run({"PYTHON_MANIFEST": "{not json"})
    assert broken.returncode == 1 and "not valid JSON" in broken.stderr


def _release_json(manifest, change=None, drop=None, add=None):
    urls = [
        {"filename": name, "digests": {"sha256": d["sha256"]}}
        for name, d in manifest["files"].items()
        if name != drop
    ]
    if change:
        urls[0]["digests"]["sha256"] = change
    if add:
        urls.append({"filename": add, "digests": {"sha256": "0" * 64}})
    return {"urls": urls}


def test_index_reporting_the_build_s_digests_passes(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert gate.compare_index(manifest, _release_json(manifest)) == []


def test_index_digest_mismatch_missing_and_extra_files_fail(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert any(
        "index reports sha256" in p
        for p in gate.compare_index(manifest, _release_json(manifest, change="f" * 64))
    )
    dropped = _release_json(manifest, drop="ragkit_dev-0.1.0.tar.gz")
    assert gate.compare_index(manifest, dropped) == ["index is missing ragkit_dev-0.1.0.tar.gz"]
    assert gate.compare_index(
        manifest, _release_json(manifest, add="ragkit_dev-0.1.0-cp311-win_amd64.whl")
    ) == ["index has an unexpected file ragkit_dev-0.1.0-cp311-win_amd64.whl"]


def test_npm_integrity_mismatch_fails(tmp_path):
    _, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(npm, "npm", "0.1.0")
    other = "sha512-" + __import__("base64").b64encode(hashlib.sha512(b"other").digest()).decode()
    assert "npm reports integrity" in gate.compare_npm(manifest, other)[0]
    assert "exactly one tarball" in gate.compare_npm({"files": {}}, other)[0]


# --- npm preflight: decided in verify, before anything is published ------------------------


def _packument(*versions, maintainers=("shamiul",)):
    return {
        "name": "rag-kit-dev",
        "versions": {version: {} for version in versions},
        "maintainers": [{"name": name, "email": f"{name}@example.org"} for name in maintainers],
    }


@pytest.mark.parametrize(
    "status, document, version, message",
    [
        (404, None, "0.1.0", "is not on npm yet"),
        (500, None, "0.1.0", "refusing to publish unverified"),
        (403, None, "0.1.0", "refusing to publish unverified"),
        (200, {"name": "rag-kit-dev", "versions": {}}, "0.1.0", "without any published version"),
        (200, {"name": "rag-kit-dev"}, "0.1.0", "without any published version"),
        (200, None, "0.1.0", "without any published version"),
        (200, ["not", "an", "object"], "0.1.0", "without any published version"),
        (200, _packument("0.0.0", "0.1.0"), "0.1.0", "rag-kit-dev@0.1.0 is already on npm"),
        (200, _packument("0.0.0", "0.1.1-rc.1"), "0.1.1rc1", "rag-kit-dev@0.1.1-rc.1 is already"),
    ],
)
def test_npm_preflight_fails_closed(status, document, version, message):
    problems = gate.npm_preflight(status, document, version)
    assert len(problems) == 1 and message in problems[0]


def test_npm_preflight_passes_once_the_placeholder_exists():
    assert gate.npm_preflight(200, _packument("0.0.0"), "0.1.0") == []
    assert gate.npm_preflight(200, _packument("0.0.0", "0.1.0"), "0.1.1") == []
    shared = _packument("0.0.0", maintainers=("other", "shamiul"))
    assert gate.npm_preflight(200, shared, "0.1.0") == []


@pytest.mark.parametrize(
    "maintainers",
    [(), ("someone-else",), ("Shamiul",), ("shamiul-x",), (" shamiul",)],
)
def test_npm_preflight_refuses_a_package_we_do_not_maintain(maintainers):
    problems = gate.npm_preflight(200, _packument("0.0.0", maintainers=maintainers), "0.1.0")
    assert len(problems) == 1 and "is not maintained by 'shamiul'" in problems[0]


@pytest.mark.parametrize(
    "document",
    [
        {"name": "rag-kit-dev", "versions": {"0.0.0": {}}},  # no maintainers field
        {"name": "rag-kit-dev", "versions": {"0.0.0": {}}, "maintainers": "shamiul"},  # wrong type
        {"name": "rag-kit-dev", "versions": {"0.0.0": {}}, "maintainers": ["shamiul"]},  # no names
    ],
)
def test_npm_preflight_refuses_unreadable_maintainers(document):
    assert "is not maintained by 'shamiul'" in gate.npm_preflight(200, document, "0.1.0")[0]


# --- fetching: no answer, or an answer that is not JSON, fails closed with a clear message -----


class _Answer:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


@pytest.mark.parametrize(
    "error, message",
    [
        (urllib.error.URLError("Name or service not known"), "cannot reach"),
        (TimeoutError("timed out"), "cannot reach"),
        (ConnectionRefusedError("refused"), "cannot reach"),
    ],
)
def test_no_answer_fails_closed_with_a_clear_message(monkeypatch, capsys, error, message):
    def no_answer(request, timeout):
        raise error

    monkeypatch.setattr(gate._OPENER, "open", no_answer)
    with pytest.raises(gate.GateError, match=message):
        gate.fetch_json("https://registry.npmjs.org/rag-kit-dev")
    assert gate.main(["npm-preflight", "--version", "0.1.0"]) == 1
    err = capsys.readouterr().err
    assert "FAIL cannot reach https://registry.npmjs.org/rag-kit-dev" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b"", b"\xff\xfe not utf-8"])
def test_an_answer_that_is_not_json_fails_closed(monkeypatch, capsys, body):
    monkeypatch.setattr(gate._OPENER, "open", lambda request, timeout: _Answer(body))
    assert gate.main(["npm-preflight", "--version", "0.1.0"]) == 1
    assert "with a body that is not JSON" in capsys.readouterr().err


def test_an_http_error_is_still_returned_as_a_status(monkeypatch):
    def not_found(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(gate._OPENER, "open", not_found)
    assert gate.fetch_json("https://registry.npmjs.org/rag-kit-dev") == (404, None)


@pytest.mark.parametrize("target", [
    "https://evil.example/pypi/ragkit-dev/0.1.0/json",     # another host
    "http://pypi.org/pypi/ragkit-dev/0.1.0/json",          # https -> http
    "https://pypi.org:8443/pypi/ragkit-dev/0.1.0/json",    # another port
    "https://pypi.org.evil.example/pypi/ragkit-dev/json",  # look-alike host
])
def test_a_redirect_to_another_origin_is_refused(target):
    request = urllib.request.Request("https://pypi.org/pypi/ragkit-dev/0.1.0/json",
                                     headers={"Authorization": "Bearer secret"})
    with pytest.raises(gate.GateError, match="another host or scheme"):
        gate._SameOriginRedirects().redirect_request(request, None, 301, "Moved", {}, target)


def test_a_redirect_on_the_same_origin_is_followed():
    request = urllib.request.Request("https://pypi.org/pypi/RagKit-Dev/0.1.0/json")
    target = "https://pypi.org/pypi/ragkit-dev/0.1.0/json"
    followed = gate._SameOriginRedirects().redirect_request(request, None, 301, "Moved", {},
                                                            target)
    assert followed.full_url == target


def test_fetch_json_uses_the_same_origin_opener():
    assert any(isinstance(h, gate._SameOriginRedirects) for h in gate._OPENER.handlers)
    # No plain redirect handler next to it that would follow anything.
    assert [type(h) for h in gate._OPENER.handlers
            if isinstance(h, urllib.request.HTTPRedirectHandler)] == [gate._SameOriginRedirects]


def test_npm_preflight_cli_reads_the_registry(monkeypatch, capsys):
    urls = []

    def missing(url, token=None):
        urls.append(url)
        return 404, None

    monkeypatch.setattr(gate, "fetch_json", missing)
    assert gate.main(["npm-preflight", "--version", "0.1.0"]) == 1
    assert urls == ["https://registry.npmjs.org/rag-kit-dev"]
    assert "is not on npm yet" in capsys.readouterr().err
    monkeypatch.setattr(gate, "fetch_json", lambda url, token=None: (200, _packument("0.0.0")))
    assert gate.main(["npm-preflight", "--version", "0.1.0"]) == 0


def test_npm_preflight_refuses_a_version_that_was_unpublished():
    # npm drops an unpublished version from `versions` but keeps it in `time`, and
    # never accepts it again: this must fail before PyPI, not in the npm job.
    document = _packument("0.0.0")
    document["time"] = {"created": "x", "modified": "x", "0.0.0": "x", "0.1.0": "x"}
    problems = gate.npm_preflight(200, document, "0.1.0")
    assert len(problems) == 1 and "published and then unpublished" in problems[0]
    document["time"] = {"created": "x", "modified": "x", "0.0.0": "x"}
    assert gate.npm_preflight(200, document, "0.1.0") == []


# --- resume: a re-run uploads only what the registry does not already have -----------------


def test_upload_plan_uploads_everything_when_the_release_is_absent(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert gate.python_upload_plan(manifest, 404, None) == (sorted(manifest["files"]), [])


def test_upload_plan_skips_files_already_published_with_the_same_bytes(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert gate.python_upload_plan(manifest, 200, _release_json(manifest)) == ([], [])
    # The wheel went up, the sdist did not (an interrupted upload): finish with the sdist.
    partial = _release_json(manifest, drop="ragkit_dev-0.1.0.tar.gz")
    assert gate.python_upload_plan(manifest, 200, partial) == (["ragkit_dev-0.1.0.tar.gz"], [])


@pytest.mark.parametrize("status, answer, message", [
    (200, "changed", "published from other files"),
    (200, "extra", "which this build did not produce"),
    (200, {"info": {}}, "without a file list"),
    (200, None, "without a file list"),
    (500, None, "refusing to upload unverified"),
    (403, None, "refusing to upload unverified"),
])
def test_upload_plan_fails_closed_on_anything_else(tmp_path, status, answer, message):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    if answer == "changed":
        answer = _release_json(manifest, change="f" * 64)
    elif answer == "extra":
        answer = _release_json(manifest, add="ragkit_dev-0.1.0-cp311-win_amd64.whl")
    upload, problems = gate.python_upload_plan(manifest, status, answer)
    assert upload == [] and problems and message in problems[0]


def _plan_cli(monkeypatch, tmp_path, dist, manifest, answer, fetched=True):
    urls = []

    def index(url, token=None):
        urls.append(url)
        return answer

    monkeypatch.setattr(gate, "fetch_json", index)
    monkeypatch.setenv("PYTHON_MANIFEST", json.dumps(manifest))
    out = tmp_path / "github_output"
    code = gate.main(["--github-output", str(out), "upload-plan", "--index", "pypi",
                      "--dir", str(dist), "--version", "0.1.0"])
    # Exactly one read of exactly this release, or none when the local files fail first.
    assert urls == (["https://pypi.org/pypi/ragkit-dev/0.1.0/json"] if fetched else [])
    return code, out.read_text(encoding="utf-8") if out.exists() else None


def test_upload_plan_cli_leaves_only_the_missing_files(monkeypatch, tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    partial = _release_json(manifest, drop="ragkit_dev-0.1.0.tar.gz")
    code, output = _plan_cli(monkeypatch, tmp_path, dist, manifest, (200, partial))
    assert code == 0 and output == "upload=true\n"
    assert sorted(p.name for p in dist.iterdir()) == ["ragkit_dev-0.1.0.tar.gz"]


def test_upload_plan_cli_uploads_nothing_when_all_is_published(monkeypatch, tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    code, output = _plan_cli(monkeypatch, tmp_path, dist, manifest,
                             (200, _release_json(manifest)))
    assert code == 0 and output == "upload=false\n"


def test_upload_plan_cli_fails_closed_and_keeps_the_files(monkeypatch, tmp_path, capsys):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    changed = _release_json(manifest, change="f" * 64)
    code, output = _plan_cli(monkeypatch, tmp_path, dist, manifest, (200, changed))
    assert code == 1 and output is None  # no upload=... at all on failure
    assert "published from other files" in capsys.readouterr().err
    assert len(list(dist.iterdir())) == 2


def test_upload_plan_cli_verifies_the_local_files_first(monkeypatch, tmp_path, capsys):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    (dist / "ragkit_dev-0.1.0.tar.gz").write_bytes(b"tampered")
    code, output = _plan_cli(monkeypatch, tmp_path, dist, manifest, (404, None), fetched=False)
    assert code == 1 and output is None
    assert "does not match the build's" in capsys.readouterr().err


# --- yanked and ambiguous file lists: never "already published", in plan or check ----------


WHEEL, SDIST = "ragkit_dev-0.1.0-py3-none-any.whl", "ragkit_dev-0.1.0.tar.gz"


def _yanked(manifest, name=WHEEL, drop=None):
    """Every file the build has, with the build's sha256, but `name` yanked on the index."""
    release = _release_json(manifest, drop=drop)
    for entry in release["urls"]:
        entry["yanked"] = entry["filename"] == name
        entry["yanked_reason"] = "broken" if entry["yanked"] else None
    return release


def test_a_yanked_file_with_matching_hashes_is_not_an_identical_release(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    upload, problems = gate.python_upload_plan(manifest, 200, _yanked(manifest))
    assert upload == [] and problems == [
        f"the index reports {WHEEL} as yanked: this version was withdrawn, "
        "release the next version"]
    assert gate.compare_index(manifest, _yanked(manifest)) == problems
    # Not yanked (False, as PyPI reports it) is still the identical release.
    assert gate.python_upload_plan(manifest, 200, _yanked(manifest, name=None)) == ([], [])
    assert gate.compare_index(manifest, _yanked(manifest, name=None)) == []


def test_a_yanked_file_blocks_completing_a_partial_release(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    partial = _yanked(manifest, name=WHEEL, drop=SDIST)  # the sdist would otherwise go up
    upload, problems = gate.python_upload_plan(manifest, 200, partial)
    assert upload == [] and "as yanked" in problems[0]


def test_upload_plan_cli_refuses_a_yanked_release_and_keeps_the_files(monkeypatch, tmp_path,
                                                                    capsys):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    code, output = _plan_cli(monkeypatch, tmp_path, dist, manifest, (200, _yanked(manifest)))
    assert code == 1 and output is None  # no upload=false: the upload is not skipped
    assert f"FAIL the index reports {WHEEL} as yanked" in capsys.readouterr().err
    assert sorted(p.name for p in dist.iterdir()) == [WHEEL, SDIST]


def _check_index_cli(monkeypatch, manifest, answers):
    """check-index --wait 600 against a sequence of index answers; sleeping is instant."""
    answers, sleeps = list(answers), []
    monkeypatch.setattr(gate, "fetch_json", lambda url, token=None: answers.pop(0))
    monkeypatch.setattr(gate.time, "sleep", sleeps.append)
    monkeypatch.setenv("PYTHON_MANIFEST", json.dumps(manifest))
    code = gate.main(["check-index", "--index", "pypi", "--version", "0.1.0", "--wait", "600"])
    return code, sleeps, answers


def test_check_index_fails_at_once_on_a_yanked_release(monkeypatch, tmp_path, capsys):
    # The upload was skipped (or the file was yanked meanwhile): verification must fail,
    # immediately, instead of waiting for it to "propagate".
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    code, sleeps, _ = _check_index_cli(monkeypatch, manifest, [(200, _yanked(manifest))])
    assert code == 1 and sleeps == []
    assert "as yanked" in capsys.readouterr().err


def test_check_index_waits_only_for_files_that_are_still_missing(monkeypatch, tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    answers = [(404, None), (200, _release_json(manifest, drop=SDIST)),
               (200, _release_json(manifest))]
    code, sleeps, left = _check_index_cli(monkeypatch, manifest, answers)
    assert code == 0 and len(sleeps) == 2 and left == []


@pytest.mark.parametrize("answer", ["missing-sdist", "absent", "unreachable", "complete"])
def test_check_index_without_wait_looks_once(monkeypatch, tmp_path, capsys, answer):
    """How the npm job checks PyPI: one look. By then PyPI has served the release to
    smoke-pypi, so a file that is missing now is a failure, not propagation."""
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    calls, sleeps = [], []

    def index(url, token=None):
        calls.append(url)
        if answer == "unreachable":
            raise gate.GateError([f"cannot reach {url} (URLError: down)"])
        return {"missing-sdist": (200, _release_json(manifest, drop=SDIST)),
                "absent": (404, None),
                "complete": (200, _release_json(manifest))}[answer]

    monkeypatch.setattr(gate, "fetch_json", index)
    monkeypatch.setattr(gate.time, "sleep", sleeps.append)
    monkeypatch.setenv("PYTHON_MANIFEST", json.dumps(manifest))
    code = gate.main(["check-index", "--index", "pypi", "--version", "0.1.0"])
    assert calls == ["https://pypi.org/pypi/ragkit-dev/0.1.0/json"] and sleeps == []
    assert code == (0 if answer == "complete" else 1)
    if answer != "complete":
        assert "FAIL" in capsys.readouterr().err


def test_check_index_does_not_wait_when_a_missing_file_comes_with_a_wrong_hash(monkeypatch,
                                                                              tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    release = _release_json(manifest, drop=SDIST, change="f" * 64)
    code, sleeps, _ = _check_index_cli(monkeypatch, manifest, [(200, release)])
    assert code == 1 and sleeps == []


def _sha(manifest, name):
    return manifest["files"][name]["sha256"]


@pytest.mark.parametrize("entries, message", [
    (lambda m: ["not an object", {"filename": SDIST, "digests": {"sha256": _sha(m, SDIST)}}],
     "file entry that is not an object"),
    (lambda m: [{"digests": {"sha256": _sha(m, WHEEL)}}], "without a file name"),
    (lambda m: [{"filename": "", "digests": {"sha256": _sha(m, WHEEL)}}], "without a file name"),
    (lambda m: [{"filename": 7, "digests": {"sha256": _sha(m, WHEEL)}}], "without a file name"),
    # A mismatching entry hidden behind a matching one, in either order.
    (lambda m: [{"filename": WHEEL, "digests": {"sha256": "f" * 64}},
                {"filename": WHEEL, "digests": {"sha256": _sha(m, WHEEL)}},
                {"filename": SDIST, "digests": {"sha256": _sha(m, SDIST)}}],
     f"lists {WHEEL} more than once"),
    (lambda m: [{"filename": WHEEL, "digests": {"sha256": _sha(m, WHEEL)}},
                {"filename": WHEEL, "digests": {"sha256": "f" * 64}},
                {"filename": SDIST, "digests": {"sha256": _sha(m, SDIST)}}],
     f"lists {WHEEL} more than once"),
])
def test_an_ambiguous_file_list_fails_closed_in_plan_and_check(tmp_path, entries, message):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    release = {"urls": entries(manifest)}
    upload, problems = gate.python_upload_plan(manifest, 200, release)
    assert upload == [] and any(message in p for p in problems), problems
    assert any(message in p for p in gate.compare_index(manifest, release))


@pytest.mark.parametrize("digests", ["sha256-of-something", ["a"], 5, None, "absent"])
def test_digests_that_are_not_an_object_fail_closed_without_a_traceback(monkeypatch, tmp_path,
                                                                       capsys, digests):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    release = _release_json(manifest)
    entry = next(u for u in release["urls"] if u["filename"] == WHEEL)
    if digests == "absent":
        del entry["digests"]
    else:
        entry["digests"] = digests
    upload, problems = gate.python_upload_plan(manifest, 200, release)
    assert upload == [] and problems == [
        f"the index lists {WHEEL} without a digests object: "
        f"{None if digests == 'absent' else digests!r}"]
    assert problems[0] in gate.compare_index(manifest, release)
    # The same answer through check-index (as the npm job runs it): an error, at once.
    code, sleeps, _ = _check_index_cli(monkeypatch, manifest, [(200, release)])
    err = capsys.readouterr().err
    assert code == 1 and sleeps == [] and "without a digests object" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("release", [None, ["not", "an", "object"], {"info": {}},
                                     {"urls": "x"}])
def test_compare_index_fails_closed_without_a_file_list(tmp_path, release):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert "without a file list" in gate.compare_index(manifest, release)[0]


def _npm_document(manifest, *versions, integrity=None, times=()):
    document = _packument("0.0.0", *versions)
    [(_, digests)] = manifest["files"].items()
    for version in versions:
        document["versions"][version] = {
            "dist": {"integrity": integrity or f"sha512-{digests['sha512']}"}}
    if times:
        document["time"] = {version: "x" for version in times}
    return document


def test_npm_publish_plan(tmp_path):
    _, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(npm, "npm", "0.1.0")
    assert gate.npm_publish_plan(manifest, 200, _npm_document(manifest), "0.1.0") == (True, [])
    # Published by an earlier attempt whose post-check failed: do not publish again.
    published = _npm_document(manifest, "0.1.0")
    assert gate.npm_publish_plan(manifest, 200, published, "0.1.0") == (False, [])


@pytest.mark.parametrize("status, kind, message", [
    (200, "other-bytes", "already on npm from other files"),
    (200, "unpublished", "published and then unpublished"),
    (404, None, "refusing to publish unverified"),
    (500, None, "refusing to publish unverified"),
    (200, "not-an-object", "refusing to publish unverified"),
])
def test_npm_publish_plan_fails_closed(tmp_path, status, kind, message):
    _, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(npm, "npm", "0.1.0")
    document = {
        "other-bytes": _npm_document(manifest, "0.1.0", integrity="sha512-other"),
        "unpublished": _npm_document(manifest, times=("0.0.0", "0.1.0")),
        "not-an-object": ["not", "an", "object"],
    }.get(kind)
    publish, problems = gate.npm_publish_plan(manifest, status, document, "0.1.0")
    assert publish is False and len(problems) == 1 and message in problems[0]


def test_npm_publish_plan_cli(monkeypatch, tmp_path):
    _, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(npm, "npm", "0.1.0")
    monkeypatch.setenv("NPM_MANIFEST", json.dumps(manifest))
    out = tmp_path / "github_output"
    for document, expected in ((_npm_document(manifest), "publish=true\n"),
                               (_npm_document(manifest, "0.1.0"), "publish=false\n")):
        monkeypatch.setattr(gate, "fetch_json", lambda url, token=None, d=document: (200, d))
        assert gate.main(["--github-output", str(out), "npm-publish-plan",
                          "--version", "0.1.0"]) == 0
        assert out.read_text(encoding="utf-8") == expected
        out.unlink()
    monkeypatch.setattr(gate, "fetch_json", lambda url, token=None: (503, None))
    assert gate.main(["--github-output", str(out), "npm-publish-plan", "--version", "0.1.0"]) == 1
    assert not out.exists()


# --- R3: environment protection ----------------------------------------------------------


def _environment(reviewers=1, bypass=False, custom=True, protected_branches=False):
    rules = [{"type": "wait_timer", "wait_timer": 0}]
    if reviewers is not None:
        rules.append(
            {
                "type": "required_reviewers",
                "reviewers": [{"type": "User", "reviewer": {"login": "owner"}}] * reviewers,
            }
        )
    return {
        "name": "pypi",
        "can_admins_bypass": bypass,
        "protection_rules": rules,
        "deployment_branch_policy": {
            "protected_branches": protected_branches,
            "custom_branch_policies": custom,
        },
    }


TAG_ONLY = {"total_count": 1, "branch_policies": [{"name": "v*", "type": "tag"}]}


def test_a_protected_environment_passes():
    assert gate.evaluate_environment("pypi", _environment(), TAG_ONLY) == []


@pytest.mark.parametrize(
    "environment, policies, message",
    [
        (None, None, "does not exist (GitHub would create it unprotected)"),
        (_environment(reviewers=None), TAG_ONLY, "has no required reviewers"),
        (_environment(reviewers=0), TAG_ONLY, "has no required reviewers"),
        (_environment(bypass=True), TAG_ONLY, "lets administrators bypass"),
        (_environment(custom=False), TAG_ONLY, "only from selected tags"),
        (_environment(custom=False, protected_branches=True), None, "only from selected tags"),
        (_environment(), {"branch_policies": []}, "deployment policies are []"),
        (_environment(), {"branch_policies": [{"name": "v*", "type": "branch"}]}, "expected only"),
        (_environment(), {"branch_policies": [{"name": "*", "type": "tag"}]}, "expected only"),
        (
            _environment(),
            {
                "branch_policies": [
                    {"name": "v*", "type": "tag"},
                    {"name": "main", "type": "branch"},
                ]
            },
            "expected only",
        ),
    ],
)
def test_unprotected_environments_fail_closed(environment, policies, message):
    assert any(message in p for p in gate.evaluate_environment("pypi", environment, policies))


def test_unreadable_environments_fail_closed(monkeypatch):
    monkeypatch.setattr(gate, "fetch_json", lambda url, token=None: (403, None))
    problems = gate.check_environments("owner/repo", ["pypi"], "token")
    assert problems and "refusing to publish unverified" in problems[0]


def test_missing_environment_via_api_fails(monkeypatch):
    monkeypatch.setattr(gate, "fetch_json", lambda url, token=None: (404, None))
    assert "does not exist" in gate.check_environments("owner/repo", ["npm"], "token")[0]


def test_environment_check_needs_a_token(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert gate.main(["check-environments", "--repo", "o/r", "--environments", "pypi"]) == 1
