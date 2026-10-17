"""Structure of .github/workflows/release.yml and ci.yml: who can publish, when, and what.

The job graph is evaluated the way GitHub schedules it: a job runs only if every
job it needs ran (and succeeded) and its `if:` is true. Conditions are limited to
the exact forms below so the evaluation cannot silently diverge from GitHub's.
"""

import re

import pytest

from tests.conftest import ROOT

yaml = pytest.importorskip("yaml")

WORKFLOWS = ROOT / ".github" / "workflows"
pytestmark = pytest.mark.skipif(not (WORKFLOWS / "release.yml").exists(),
                                reason="workflows are not part of the sdist")

PRODUCTION_GATE = "needs.verify.outputs.production == 'true'"
PRODUCTION_JOBS = {"publish-pypi", "smoke-pypi", "publish-npm", "smoke-npm"}
PUBLISH_JOBS = {"publish-testpypi": "testpypi", "publish-pypi": "pypi", "publish-npm": "npm"}
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _load(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as True
    return data


@pytest.fixture(scope="module")
def release():
    return _load("release.yml")


@pytest.fixture(scope="module")
def ci():
    return _load("ci.yml")


def _needs(job):
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _evaluate(condition, production):
    """GitHub semantics for the only condition this workflow may use (case-insensitive ==)."""
    if condition is None:
        return True
    assert condition == PRODUCTION_GATE, f"unexpected job condition: {condition!r}"
    return production.lower() == "true"


def _runnable(release, production):
    jobs, ran = release["jobs"], set()
    pending = dict(jobs)
    while pending:
        progressed = False
        for name, job in list(pending.items()):
            needs = _needs(job)
            if all(n not in pending for n in needs):
                if all(n in ran for n in needs) and _evaluate(job.get("if"), production):
                    ran.add(name)
                del pending[name]
                progressed = True
        assert progressed, f"cycle in needs: {sorted(pending)}"
    return ran


# --- R1/R4: rehearsal can never reach production ----------------------------------------


def test_rehearsal_graph_never_reaches_production_publishing(release):
    ran = _runnable(release, production="false")
    assert ran == {"verify", "ci", "publish-testpypi", "e2e-testpypi"}
    assert not ran & PRODUCTION_JOBS


def test_release_graph_reaches_every_stage_in_order(release):
    assert _runnable(release, production="true") == set(release["jobs"])
    order = ["publish-testpypi", "e2e-testpypi", "publish-pypi", "smoke-pypi", "publish-npm"]
    for earlier, later in zip(order, order[1:]):
        assert earlier in _needs(release["jobs"][later])


@pytest.mark.parametrize("value", ["false", "", "False", "yes", "1", "production"])
def test_anything_but_true_skips_production(release, value):
    assert not _runnable(release, production=value) & PRODUCTION_JOBS


def test_every_production_job_checks_the_trusted_output_itself(release):
    for name in PRODUCTION_JOBS:
        job = release["jobs"][name]
        assert job.get("if") == PRODUCTION_GATE, name
        assert "verify" in _needs(job), f"{name} must read verify's output directly"
    # Any job downstream of a production publish is itself gated.
    for name, job in release["jobs"].items():
        if set(_needs(job)) & PRODUCTION_JOBS:
            assert job.get("if") == PRODUCTION_GATE, name


def test_no_condition_ever_compares_the_raw_stage_input(release):
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert text.count("inputs.stage") == 1  # only passed to the authorize step's env
    authorize = next(s for s in release["jobs"]["verify"]["steps"] if s.get("id") == "authorize")
    assert authorize["env"]["STAGE"] == "${{ inputs.stage }}"
    assert "release_gate.py" in authorize["run"] and "authorize" in authorize["run"]
    assert release["jobs"]["verify"]["outputs"]["production"] == (
        "${{ steps.authorize.outputs.production }}")


def test_stage_input_is_a_choice_of_exactly_two(release):
    stage = release["on"]["workflow_dispatch"]["inputs"]["stage"]
    assert stage["type"] == "choice" and stage["options"] == ["rehearsal", "release"]
    assert set(release["on"]) == {"workflow_dispatch"}


# --- R2: artifacts are verified before and after publishing --------------------------------


def _step_index(steps, predicate):
    return next((i for i, s in enumerate(steps) if predicate(s)), None)


@pytest.mark.parametrize("job_name, kind, after", [
    ("publish-testpypi", "python", "check-index --index testpypi"),
    ("publish-pypi", "python", "check-index --index pypi"),
    ("publish-npm", "npm", "check-npm"),
])
def test_publish_jobs_verify_before_and_check_after(release, job_name, kind, after):
    steps = release["jobs"][job_name]["steps"]
    verify = _step_index(steps, lambda s: f"verify-artifacts --kind {kind}" in s.get("run", ""))
    publish = _step_index(steps, lambda s: "gh-action-pypi-publish" in s.get("uses", "")
                          or "npm publish" in s.get("run", ""))
    check = _step_index(steps, lambda s: after in s.get("run", ""))
    assert verify is not None and publish is not None and check is not None
    assert verify < publish < check
    manifest = "PYTHON_MANIFEST" if kind == "python" else "NPM_MANIFEST"
    for index in (verify, check):
        assert steps[index]["env"][manifest] == f"${{{{ needs.ci.outputs.{kind}-manifest }}}}"
        assert steps[index]["env"]["VERSION"] == "${{ needs.verify.outputs.version }}"
    assert "ci" in _needs(release["jobs"][job_name])


def test_manifests_come_from_the_ci_build_job(ci):
    outputs = ci["on"]["workflow_call"]["outputs"]
    assert outputs["python-manifest"]["value"] == "${{ jobs.build.outputs.python-manifest }}"
    assert outputs["npm-manifest"]["value"] == "${{ jobs.build.outputs.npm-manifest }}"
    build = ci["jobs"]["build"]
    assert build["outputs"]["python-manifest"] == "${{ steps.manifest.outputs.python-manifest }}"
    manifest = next(s for s in build["steps"] if s.get("id") == "manifest")
    assert "release_gate.py" in manifest["run"] and " manifest " in manifest["run"]
    runs = [s.get("run", "") for s in build["steps"]]
    assert any("check_dist.py" in r for r in runs)
    assert any("check_sdist_build.py" in r for r in runs)
    # uv build leaves a .gitignore in dist/; it must be gone before the strict manifest.
    build_step = _step_index(build["steps"],
                             lambda s: "uv build --out-dir dist" in s.get("run", ""))
    manifest_step = _step_index(build["steps"], lambda s: s.get("id") == "manifest")
    assert "rm -f dist/.gitignore" in build["steps"][build_step]["run"]
    assert build_step < manifest_step


def test_npm_publish_is_the_verified_file_without_scripts(release):
    run = next(s["run"] for s in release["jobs"]["publish-npm"]["steps"]
               if "npm publish" in s.get("run", ""))
    assert "--ignore-scripts" in run and "--provenance" in run and "--access public" in run
    assert "rag-kit-dev-${NPM_VERSION}.tgz" in run


# --- R3 and permissions -------------------------------------------------------------------


def test_only_publish_jobs_get_oidc_and_each_has_its_environment(release, ci):
    assert release["permissions"] == {"contents": "read"}
    assert ci["permissions"] == {"contents": "read"}
    for name, job in release["jobs"].items():
        permissions = job.get("permissions", {})
        if name in PUBLISH_JOBS:
            assert job["environment"]["name"] == PUBLISH_JOBS[name]
            assert permissions == {"contents": "read", "id-token": "write"}
        else:
            assert "environment" not in job, name
            assert "id-token" not in permissions, name
            assert "write" not in permissions.values(), name
    for name, job in ci["jobs"].items():
        assert "permissions" not in job and "environment" not in job, name


def test_verify_checks_the_environments_the_stage_uses(release):
    verify = release["jobs"]["verify"]
    assert verify["permissions"] == {"contents": "read", "actions": "read"}
    step = next(s for s in verify["steps"] if "check-environments" in s.get("run", ""))
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "environments=testpypi" in step["run"]
    assert "environments=testpypi,pypi,npm" in step["run"]


def test_a_release_checks_npm_before_anything_is_published(release):
    steps = release["jobs"]["verify"]["steps"]
    index = _step_index(steps, lambda s: "npm-preflight" in s.get("run", ""))
    assert index is not None
    step = steps[index]
    # Only for a release: a rehearsal never touches npm and must not depend on it.
    assert step["if"] == "steps.authorize.outputs.production == 'true'"
    assert step["env"]["VERSION"] == "${{ steps.authorize.outputs.version }}"
    assert index > _step_index(steps, lambda s: s.get("id") == "authorize")
    # verify runs first, and every publish job needs it, so nothing is published before.
    for name in PUBLISH_JOBS:
        assert "verify" in _needs(release["jobs"][name])


# --- general hardening ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ci.yml", "release.yml", "links.yml"])
def test_actions_are_pinned_and_checkouts_keep_no_credentials(name):
    for job in _load(name)["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert SHA_PIN.match(step["uses"]), step["uses"]
                if step["uses"].startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False


@pytest.mark.parametrize("name", ["ci.yml", "release.yml", "links.yml"])
def test_no_event_data_is_interpolated_into_scripts(name):
    for job in _load(name)["jobs"].values():
        for step in job.get("steps", []):
            for expression in re.findall(r"\$\{\{(.*?)\}\}", step.get("run", "")):
                assert expression.strip().startswith("matrix."), expression


def test_no_untrusted_triggers_and_pinned_release_tooling():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in text and "secrets." not in text, path.name
        assert "packaging>=" not in text, path.name
        for spec in re.findall(r"--with \"?(packaging[^\"\s]*)", text):
            assert spec == "packaging==26.3", (path.name, spec)
