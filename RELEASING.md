# Releasing rag-kit and rag-kit-dev

rag-kit (PyPI) and rag-kit-dev (npm) always share one version: the generator
installs `rag-kit==<its own version>`. Releases are published only by the
**Release** workflow (`.github/workflows/release.yml`), never from a laptop.

## One-time setup (maintainer, outside this repository)

1. **GitHub Environments** (Settings > Environments): create `testpypi`, `pypi`
   and `npm`. For each, add yourself as a **required reviewer** and limit
   deployments to tags matching `v*`.
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
   python scripts/check_versions.py --set 0.1.1     # pyproject.toml + generator/package.json
   ```
   Add a `## 0.1.1` section to CHANGELOG.md, then
   `python scripts/check_versions.py` must pass.
3. **Tag** the merged commit on `main` (`git tag v0.1.1 && git push origin v0.1.1`).
4. **Rehearse** (recommended for every release, required for the first):
   tag a pre-release such as `v0.1.1rc1` (same steps with `--set 0.1.1rc1`),
   then run *Actions > Release*, **Use workflow from** the tag,
   `stage = rehearsal`. It runs the full CI on the tag, publishes to
   **TestPyPI only** after your approval, and installs it with
   `rag-kit-dev --test-pypi` on Linux, Windows and macOS. Pre-releases are
   never published to PyPI or npm.
5. **Release**: run the workflow from the final tag with `stage = release`.
   Approve each step when asked:
   1. TestPyPI publish, then the TestPyPI end-to-end check;
   2. PyPI publish, then a check that `requirements.txt` resolves from PyPI;
   3. npm publish (only after PyPI, because the generator pins that version),
      then `npx rag-kit-dev@<version>` on all three platforms.

Each step publishes the exact files CI built and tested in that run (their
SHA-256 sums are in the job summary), and after each publish the installed
rag-kit must match those files byte for byte (`check_wheel_install.py --wheel`).

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
