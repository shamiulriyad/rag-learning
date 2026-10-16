# Releasing rag-kit and rag-kit-dev

rag-kit (PyPI) and rag-kit-dev (npm) always share one version: the generator
installs `rag-kit==<its own version>`. Releases are published only by the
**Release** workflow (`.github/workflows/release.yml`), never from a laptop.
Every release decision is made by `scripts/release_gate.py`, which is tested in
`tests/test_release_gate.py` and `tests/test_release_workflow.py`.

## One-time setup (maintainer, outside this repository) - mandatory preflight

Do all of this **before the first run** of the Release workflow. GitHub creates
a missing environment *without any protection* the first time a workflow uses
it, so a named environment alone proves nothing.

1. **GitHub Environments** (Settings > Environments): create `testpypi`, `pypi`
   and `npm`, and for each:
   - add yourself as a **required reviewer**;
   - **turn off** "Allow administrators to bypass configured protection rules";
   - set *Deployment branches and tags* to **Selected branches and tags** with
     exactly one rule: **tag** pattern `v*` (no branch rules).
   The workflow's `verify` job checks all of this through GitHub's API and
   refuses to publish if anything differs, or if it cannot read the settings.
2. **TestPyPI and PyPI**: create the project `rag-kit` through a *pending
   trusted publisher* for this repository, workflow `release.yml`, with
   environment `testpypi` (on test.pypi.org) and `pypi` (on pypi.org). No API
   tokens are created or stored.
3. **npm**: create the package `rag-kit-dev` and configure *trusted
   publishing* for this repository, workflow `release.yml`, environment `npm`.
   Publishing uses npm 11.5.1+ with provenance; no npm token is stored.
4. Optional: make the CI jobs required checks for `main` (branch protection).
   Do not make the weekly external-link check required.

## Every release

1. **Merge** the work into `main` through a pull request; CI must be green.
   README links point at `main`, so they only resolve after the merge.
2. **Version bump** in a pull request:
   ```bash
   python scripts/check_versions.py --set 0.1.1rc1   # pyproject.toml + generator/package.json
   ```
   Add a `## 0.1.1rc1` section to CHANGELOG.md; `python scripts/check_versions.py`
   must pass. Repeat later with the final version (`--set 0.1.1`).
3. **Tag** the merged commit on `main` with the canonical form of the version:
   `v0.1.1rc1` or `v0.1.1` (not `v0.1.1-rc.1`, `v0.1.1RC1` or `v0.1`).
4. **Rehearse** with the pre-release tag: *Actions > Release*, **Use workflow
   from** the tag, `stage = rehearsal`. Rehearsal accepts only pre-release tags
   and can only reach TestPyPI: the production jobs require `production=true`,
   which `verify` emits only for `stage = release` with a final version.
5. **Release** with the final tag and `stage = release` (final versions only).
   Approve each environment when asked:
   1. TestPyPI publish, then the TestPyPI end-to-end check;
   2. PyPI publish, then the generator resolving `requirements.txt` from PyPI;
   3. npm publish (only after PyPI, because the generator pins that version),
      then `npx rag-kit-dev@<version>` on all three platforms.

## What the release workflow guarantees

- `verify` (before anything else): the run starts from a `v*` tag; the stage is
  exactly `rehearsal` or `release`; the tag is canonical and matches
  pyproject.toml, package.json and CHANGELOG.md; rehearsal uses a pre-release
  and release a final version; the tagged commit is on `main`; README links
  resolve at it; the environments are protected as above.
- The full CI runs on the tag. Its build job records the expected file list,
  SHA-256 (and npm sha512 integrity) of the wheel, sdist and npm tarball, and
  checks that the sdist builds the same package as the wheel.
- Before each publish, the downloaded files must be exactly that list with
  those hashes, for the authorized version. After each publish, the hashes
  PyPI/TestPyPI report and npm's integrity must equal them, and installed
  projects must contain exactly the wheel's files.
- Only the three publish jobs can request an OIDC token; no job has secrets.

## Limitations that need a real GitHub run (not provable locally)

- **Environment checks** read `GET /repos/{repo}/environments/{name}` with the
  job token and `actions: read`. If GitHub refuses that token, `verify` fails
  closed ("cannot read environment"); then the settings must be verified by
  hand before each release and the check adjusted (for example a read-only
  token) - never removed.
- **arm64 Linux runners** (`ubuntu-24.04-arm`, used by the PyTorch end-to-end
  job): free only for public repositories. If unavailable, CI and therefore the
  release cannot complete until the matrix entry or runner is changed.
- **npm trusted publishing (OIDC)** with `setup-node`'s `registry-url` and
  `npm publish --ignore-scripts`: confirmed only by the first real release
  (rehearsals never publish to npm); if it fails, nothing is published to npm (PyPI has already been
  released and stays valid; re-run the npm job after fixing).
- Whether GitHub rejects `stage` values outside the two choices is not relied
  on: `verify` refuses anything else.

## What CI never does

No CI or release job has an API key: none is defined, and a guard step fails
the job if `GOOGLE_API_KEY` is set. No job calls Gemini, ingests a document,
or downloads an embedding model (`HF_HOME` is a temporary folder with
`HF_HUB_OFFLINE=1`; the PyTorch jobs check it is still empty).

## If something goes wrong

- A version number can never be reused on PyPI or npm.
- **PyPI**: *yank* the release on pypi.org (installs that pin it still work;
  new resolutions skip it), fix, and release the next patch version.
- **npm**: `npm deprecate rag-kit-dev@<version> "<reason>"`; unpublishing is
  possible only within 72 hours and should be a last resort.
- Because npm is published last, a failure before it leaves npm untouched.
