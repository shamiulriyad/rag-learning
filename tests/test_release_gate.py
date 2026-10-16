"""scripts/release_gate.py: release authorization, artifact integrity, environment checks."""

import hashlib
import json
import shutil
import subprocess
import sys

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
    (dist / f"rag_kit-{version}-py3-none-any.whl").write_bytes(b"wheel bytes")
    (dist / f"rag_kit-{version}.tar.gz").write_bytes(b"sdist bytes")
    (npm / f"rag-kit-dev-{gate.npm_form(version)}.tgz").write_bytes(b"npm tarball bytes")
    return dist, npm


def test_manifest_records_sha256_and_npm_integrity(tmp_path):
    dist, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    assert (
        manifest["files"]["rag_kit-0.1.0.tar.gz"]["sha256"]
        == hashlib.sha256(b"sdist bytes").hexdigest()
    )
    npm_manifest = gate.build_manifest(npm, "npm", "0.1.0")
    assert (
        gate.compare_npm(
            npm_manifest, "sha512-" + npm_manifest["files"]["rag-kit-dev-0.1.0.tgz"]["sha512"]
        )
        == []
    )


@pytest.mark.parametrize("extra, missing", [("stray.whl", None), (None, "rag_kit-0.1.0.tar.gz")])
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
    (dist / "rag_kit-0.1.0-py3-none-any.whl").write_bytes(b"tampered")
    assert any(
        "sha256" in p and "does not match the build's" in p
        for p in gate.verify_artifacts(manifest, dist, "python", "0.1.0")
    )


def test_missing_and_extra_artifacts_are_refused(tmp_path):
    dist, _ = _artifacts(tmp_path)
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    (dist / "rag_kit-0.1.0.tar.gz").unlink()
    (dist / "rag_kit-9.9.9-py3-none-any.whl").write_bytes(b"other")
    problems = gate.verify_artifacts(manifest, dist, "python", "0.1.0")
    assert "missing artifact: rag_kit-0.1.0.tar.gz" in problems
    assert "unexpected artifact: rag_kit-9.9.9-py3-none-any.whl" in problems


def test_a_manifest_for_another_version_is_refused(tmp_path):
    dist, _ = _artifacts(tmp_path, "0.1.0")
    manifest = gate.build_manifest(dist, "python", "0.1.0")
    problems = gate.verify_artifacts(manifest, dist, "python", "0.1.1")
    assert any("manifest is for python 0.1.0, expected python 0.1.1" in p for p in problems)
    assert "missing artifact: rag_kit-0.1.1.tar.gz" in problems


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
    assert gate.compare_index(manifest, _release_json(manifest, drop="rag_kit-0.1.0.tar.gz")) == [
        "index is missing rag_kit-0.1.0.tar.gz"
    ]
    assert gate.compare_index(
        manifest, _release_json(manifest, add="rag_kit-0.1.0-cp311-win_amd64.whl")
    ) == ["index has an unexpected file rag_kit-0.1.0-cp311-win_amd64.whl"]


def test_npm_integrity_mismatch_fails(tmp_path):
    _, npm = _artifacts(tmp_path)
    manifest = gate.build_manifest(npm, "npm", "0.1.0")
    other = "sha512-" + __import__("base64").b64encode(hashlib.sha512(b"other").digest()).decode()
    assert "npm reports integrity" in gate.compare_npm(manifest, other)[0]
    assert "exactly one tarball" in gate.compare_npm({"files": {}}, other)[0]


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
