"""scripts/check_versions.py and scripts/check_readme_links.py (release tooling)."""

import json
import shutil
import subprocess
import sys

import pytest

from tests.conftest import ROOT

SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(not (SCRIPTS / "check_versions.py").exists(),
                                reason="release scripts are not part of the sdist")


def _script(name, *args, cwd=ROOT):
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=120)


def _copy_project(tmp_path):
    (tmp_path / "generator").mkdir()
    for rel in ("pyproject.toml", "CHANGELOG.md", "generator/package.json"):
        shutil.copy(ROOT / rel, tmp_path / rel)
    return tmp_path


# --- versions -------------------------------------------------------------------


def test_versions_are_in_sync_in_this_checkout():
    result = _script("check_versions.py")
    assert result.returncode == 0, result.stdout
    assert "Versions are in sync." in result.stdout


def test_tag_must_match():
    package = (ROOT / "generator" / "package.json").read_text(encoding="utf-8")
    version = json.loads(package)["version"]
    assert _script("check_versions.py", "--tag", f"v{version}").returncode == 0
    wrong = _script("check_versions.py", "--tag", "v99.0.0")
    assert wrong.returncode == 1 and "does not match" in wrong.stdout
    assert _script("check_versions.py", "--tag", version).returncode == 1  # missing "v"


def test_set_bumps_both_files_and_uses_npm_prerelease_form(tmp_path):
    project = _copy_project(tmp_path)
    changelog = project / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 0.2.0rc1 (unreleased)\n", encoding="utf-8")

    result = _script("check_versions.py", "--set", "0.2.0rc1", "--root", str(project))

    assert result.returncode == 0, result.stdout
    assert 'version = "0.2.0rc1"' in (project / "pyproject.toml").read_text(encoding="utf-8")
    package = json.loads((project / "generator" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == "0.2.0-rc.1"
    assert package["name"] == "rag-kit-dev"  # the rest of package.json is kept
    tagged = _script("check_versions.py", "--root", str(project), "--tag", "v0.2.0rc1")
    assert tagged.returncode == 0


def test_mismatch_and_missing_changelog_entry_fail(tmp_path):
    project = _copy_project(tmp_path)
    package_path = project / "generator" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "9.9.9"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    result = _script("check_versions.py", "--root", str(project))

    assert result.returncode == 1
    assert "versions differ" in result.stdout


def test_changelog_needs_a_section_for_the_version(tmp_path):
    project = _copy_project(tmp_path)
    (project / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    result = _script("check_versions.py", "--root", str(project))
    assert result.returncode == 1 and "CHANGELOG.md has no" in result.stdout


# --- README links ---------------------------------------------------------------


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the git checkout")
def test_readme_links_resolve_at_head():
    result = _script("check_readme_links.py")
    assert result.returncode == 0, result.stdout


def _git_repo(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    return tmp_path


BASE = "https://github.com/shamiulriyad/rag-learning"


def test_link_problems_are_reported(tmp_path):
    repo = _git_repo(tmp_path, {
        "README.md": (f"[ok]({BASE}/blob/main/LICENSE) [folder]({BASE}/tree/main/src) "
                      f"[gone]({BASE}/blob/main/missing.py) [kind]({BASE}/blob/main/src) "
                      "[relative](LICENSE) [external](https://example.com/x)"),
        "docs/pipeline.md": "[up](../LICENSE) [bad](../nope.md) [anchor](#metadata)",
        "LICENSE": "MIT",
        "src/a.py": "",
    })
    result = _script("check_readme_links.py", "--root", str(repo))
    assert result.returncode == 1
    out = result.stdout
    assert "missing.py is missing" in out
    assert "src is tree at HEAD, expected blob" in out
    assert "relative link 'LICENSE' breaks on package index pages" in out
    assert "relative link '../nope.md' does not resolve" in out
    assert "../LICENSE" not in out and "example.com" not in out and "#metadata" not in out
    assert out.count("FAIL") == 4
