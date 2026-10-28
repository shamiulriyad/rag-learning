# Releasing ragkit-dev and rag-kit-dev

ragkit-dev (PyPI; import name `rag_kit`, command `rag-kit`) and rag-kit-dev
(npm) always share one version: the generator installs
`ragkit-dev==<its own version>`. Releases are published only by the
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

   *Capitalisation.* GitHub documents that environment names are not case
   sensitive, so an environment shown as `PyPI` is the one the workflow's
   `environment: pypi` uses (the API answers `/environments/pypi` with it).
   PyPI's trusted-publisher check also compares the environment
   case-insensitively (`_check_environment` in pypi/warehouse,
   `warehouse/oidc/models/github.py`, checked 2026-10-28). npm, however, says
   all trusted-publisher fields are case-sensitive and must be exact: the npm
   environment must be `npm`, in lower case, on both sides. Renaming `PyPI`
   to `pypi` is not required; it only makes the settings read like the
   workflow.
2. **TestPyPI and PyPI**: create the project `ragkit-dev` through a *pending
   trusted publisher* for this repository: owner `shamiulriyad`, repository
   `rag-learning`, workflow `release.yml`, environment `testpypi` (on
   test.pypi.org) and `pypi` (on pypi.org). No API tokens are created or
   stored. A pending publisher does not reserve the name; only the first
   upload does, separately on each index. TestPyPI's publisher is proven by
   the 0.1.0rc1 rehearsal; PyPI's is proven only by the first release.
3. **npm** (needed before the first `stage = release`, not for rehearsals).
   npm's documentation describes adding a trusted publisher from the
   package's own settings page; we found no documented way to set one up for
   a package that does not exist yet (PyPI has pending publishers for that).
   This is our reading of the docs, not an explicit statement by npm. This
   repository never stores an npm
   token, so the package is created once, by hand, with a placeholder:

   > **Publishing the placeholder is a deliberate, public and permanent
   > registry action.** It needs the maintainer's explicit approval at the
   > time. Anyone can see and install it; the version `0.0.0` can never be
   > reused; until 0.1.0 is published it is the package's `latest` version,
   > so `npx rag-kit-dev` meanwhile fails ("could not determine executable to
   > run") instead of creating a project. No automation in this repository
   > publishes it.

   1. On npmjs.com, enable two-factor authentication in the
      **"Authorization and writes"** mode (Account > Two-Factor Authentication),
      so that publishing asks for your 2FA code, not only logging in.
   2. Verify the maintainer identity and that the name is free:
      ```bash
      npm login                 # browser sign-in; a session on this computer only, never in CI
      npm whoami                # must print exactly: shamiul (NPM_MAINTAINER in release_gate.py)
      npm view rag-kit-dev      # must fail with E404 (the name is still free)
      ```
      If `npm whoami` prints another name, stop: change `NPM_MAINTAINER` (and
      its tests) in a pull request first. If `npm view` shows a package, stop:
      someone else has the name.
   3. In an empty folder **outside this repository**, write the placeholder.
      It must contain no executable code: only these two files.
      `package.json`:
      ```json
      {
        "name": "rag-kit-dev",
        "version": "0.0.0",
        "description": "Placeholder - install rag-kit-dev 0.1.0 or later",
        "license": "MIT",
        "repository": {
          "type": "git",
          "url": "git+https://github.com/shamiulriyad/rag-learning.git",
          "directory": "generator"
        }
      }
      ```
      No `bin`, no `scripts` (no lifecycle scripts), no `main`, no
      dependencies. `README.md`: one paragraph saying this is a placeholder
      reserving the name until 0.1.0. Check what would be published, then
      publish it:
      ```bash
      npm pack --dry-run        # must list exactly package.json and README.md
      npm publish --access public   # asks for your 2FA code
      npm view rag-kit-dev maintainers   # must list shamiul
      ```
   4. **No more than 2 days before the release run**, on npmjs.com >
      rag-kit-dev > Settings, add a *trusted publisher* for GitHub Actions
      with exactly: organization or user `shamiulriyad`, repository
      `rag-learning`, workflow filename `release.yml`, environment `npm`.
      npm's documentation (docs.npmjs.com/trusted-publishers, checked
      2026-10-28) says a new trusted publisher configuration must complete its
      first successful publish within 2 days, or it expires and can no longer
      be used or edited; check that page again before you start, as the rule
      may change. If it expired, delete it and add a new one. Then set
      *Publishing access* to "Require two-factor authentication and disallow
      tokens" (npm documents that trusted publishers keep working with it).
   5. Publishing 0.1.0 (the Release workflow) and retiring the placeholder are
      separate steps. Only after `npm view rag-kit-dev@0.1.0` shows 0.1.0 and
      `npm view rag-kit-dev dist-tags.latest` is `0.1.0`:
      `npm deprecate rag-kit-dev@0.0.0 "placeholder, use 0.1.0 or later"`
      (a manual, approved action, with your 2FA code).

   Before anything is published (in `verify`, before TestPyPI), a release
   refuses to start unless npm's public metadata shows `rag-kit-dev` with at
   least one version, `shamiul` among its maintainers (`NPM_MAINTAINER` in
   `scripts/release_gate.py`), and neither the version being released nor a
   trace of it having been published and unpublished; it also refuses if the
   registry cannot be reached or read. It cannot see the trusted-publisher
   setting: if that (or OIDC, or the registry) fails, npm fails **after**
   PyPI has published; see "If a release fails part-way" below.
   Publishing uses npm 11.5.1+ on Node 24 (npm requires Node 22.14.0+ for
   trusted publishing) with provenance; no npm token is stored.
4. **Artifact retention** (Settings > Actions > General > *Artifact and log
   retention*): at least 30 days. A release keeps its verified files for 30
   days so failed jobs can be re-run; a lower repository limit shortens that.
5. Optional: make the CI jobs required checks for `main` (branch protection).
   Do not make the weekly external-link check required.

## Every release

1. **Merge** the work into `main` through a pull request; CI must be green.
   README links point at `main`, so they only resolve after the merge.
2. **Version bump** in its own pull request (never directly on `main`):
   ```bash
   python scripts/check_versions.py --set 0.1.1rc1   # pyproject.toml + generator/package.json
   ```
   Add a `## 0.1.1rc1` section to CHANGELOG.md; `python scripts/check_versions.py`
   must pass. Repeat later with the final version (`--set 0.1.1`). For a final
   version the heading must carry the release date, not "unreleased":
   `python scripts/check_versions.py --tag v0.1.1` checks that, and so does
   `verify`.
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

### Preparing 0.1.0 (the first release)

`0.1.0rc1` was rehearsed on TestPyPI. In one pull request:

```bash
python scripts/check_versions.py --set 0.1.0      # 0.1.0 in both files
```

In CHANGELOG.md, change `## 0.1.0 (unreleased)` to `## 0.1.0 (YYYY-MM-DD)` and
keep the `0.1.0rc1` section as history. Then
`python scripts/check_versions.py --tag v0.1.0` must pass. Stage only
`pyproject.toml`, `generator/package.json` and `CHANGELOG.md`. After the merge,
finish the npm setup above (placeholder, then the trusted publisher within 2
days of the run), tag the merge commit `v0.1.0` and run `stage = release`.

## What the release workflow guarantees

- `verify` (before anything else): the run starts from a `v*` tag; the stage is
  exactly `rehearsal` or `release`; the tag is canonical and matches
  pyproject.toml, package.json and CHANGELOG.md; rehearsal uses a pre-release
  and release a final version; the tagged commit is on `main`; README links
  resolve at it; the environments are protected as above. For a release, npm's
  public metadata must show `rag-kit-dev` (the placeholder above) maintained by
  `shamiul` and without the version being released. npm can still fail after
  PyPI for reasons this cannot see (trusted publisher, OIDC, registry outage).
- The full CI runs on the tag. Its build job builds the wheel, sdist and npm
  tarball **once**, records their file list, SHA-256 (and npm sha512
  integrity), and checks that the sdist builds the same package as the wheel.
  Every later job downloads these same files; nothing is rebuilt.
- Before each publish, the downloaded files must be exactly that list with
  those hashes, for the authorized version. Then the upload plan asks the
  registry what it already has for this version: files it already serves with
  exactly these hashes are not uploaded again, anything else it has for this
  version (other bytes, unexpected or yanked files, an ambiguous file list)
  fails the job, and only the missing files are published. After each
  publish, the hashes PyPI/TestPyPI report and npm's integrity must equal the
  build's, and installed projects must contain exactly the wheel's files.
- Order: TestPyPI, its end-to-end check, PyPI, its end-to-end check, npm. A
  failure stops everything after it, so npm can lag behind PyPI but never get
  ahead of it. Right before it plans and publishes, the npm job looks at PyPI
  once more (`check-index --index pypi`, no waiting): PyPI must still serve
  exactly the build's files, none of them yanked, or npm is not published.
- Only the three publish jobs can request an OIDC token; no job has secrets.

## If a release fails part-way

Package versions are permanent: a file name on PyPI/TestPyPI and a version on
npm can be published only once, even after deletion. So never "try again" by
hand. Look at which job failed, then:

- **Use "Re-run failed jobs"** on the same run (Actions > the run > Re-run jobs
  > Re-run failed jobs). GitHub documents that a re-run uses the same commit
  and ref and is possible for 30 days after the run; a release keeps its
  files for 30 days. The design relies on two things GitHub does not spell
  out, which the first real recovery will confirm: that jobs which succeeded
  keep their outputs (the version, the build's manifest), and that the re-run
  jobs can download the run's artifacts. If either is missing, the jobs fail
  closed ("manifest did not arrive", or the download fails) without uploading
  anything; see "If a re-run cannot use the original build" below. Check that
  the jobs after the failed one start too; if one stays skipped, re-run it as
  a specific job. Approve environment jobs when GitHub asks.
- **Do not use "Re-run all jobs"** for a release that has published anything.
  It rebuilds everything; if the new files are not byte-identical to the
  published ones, the upload plan refuses (fails closed), and once npm has the
  version, `verify` refuses the whole run.

| What failed | State | What to do |
| --- | --- | --- |
| `verify` or `ci` | nothing published | Fix the cause. Re-run if it was transient. If a code change is needed and nothing was published anywhere, merge it, delete the unused tag (`git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`), tag the new `main` commit and start a new run. |
| `publish-testpypi`, before or during the upload | TestPyPI may have some files | Re-run failed jobs: the plan uploads only what is missing. |
| `publish-testpypi`, after the upload (TestPyPI did not report the hashes within 10 minutes) | TestPyPI has the files | Wait, then re-run failed jobs: nothing is uploaded again, the hashes are compared again. |
| `e2e-testpypi` | TestPyPI only; production untouched | Transient (network, runner): re-run failed jobs. A real defect: fix it and release the next patch version; this version is used up on TestPyPI. |
| `publish-pypi` (before, during or after the upload) | PyPI may have some or all files | As for TestPyPI: re-run failed jobs. If the upload plan reports other bytes on PyPI, stop: do not try to finish this version. |
| `smoke-pypi` | PyPI has the version, npm does not | Transient: re-run failed jobs. A real defect: yank the version on pypi.org (installs that pin it keep working) and release the next patch version; npm never gets the broken one. |
| `publish-npm` before publishing (trusted publisher missing or expired, OIDC refused, registry down) | PyPI has the version, npm does not; `npx rag-kit-dev` still gives the placeholder | Fix the npm setting (a new trusted publisher if it expired), then re-run failed jobs within 30 days. PyPI's release stays valid. |
| `publish-npm` after publishing (npm did not report the integrity within 10 minutes) | npm has the version | Re-run failed jobs: the plan sees the identical version and does not publish again. |
| `smoke-npm` | both published | Transient: re-run failed jobs. A real defect: `npm deprecate rag-kit-dev@<version> "<reason>"`, yank the PyPI version, release the next patch version on both. |
| `publish-npm`, at "PyPI still serves exactly the trusted build" | PyPI's release is yanked, incomplete or differs; npm untouched | Nothing was published to npm. Do not re-run until you know why: a yanked version is never completed. Release the next patch version. |
| Any job, after you yanked the version on PyPI/TestPyPI | the version is withdrawn | Do not try to finish it: the PyPI/TestPyPI upload plans, their post-upload checks and the npm job's PyPI check all refuse a release with a yanked file, even when every hash matches. Release the next patch version. Once npm has published, yanking PyPI does not change npm: deprecate the npm version too. |
| A re-run is no longer possible (after 30 days), or cannot use the original build | depends | See below. |

### If a re-run cannot use the original build

The manifest and the artifacts of the original run are what tie every publish
to one verified build. If a re-run reports "manifest did not arrive", cannot
download `python-dist`/`npm-dist`, or is past the 30-day window:

1. Do **not** upload anything by hand, and do not copy files from another run.
2. Start a **new** run of the Release workflow from the same tag. It builds and
   tests everything again and records a new manifest.
3. A fresh run is **not guaranteed to complete**:
   - If npm already has the version, `verify` refuses the new run before
     anything else (its npm preflight never accepts a version npm already
     has). There is then nothing left to publish; check the release by hand
     (`npx rag-kit-dev@<version> my-test --no-install`) or, if it is broken,
     go to step 4.
   - Otherwise its upload plans compare the new files with what the
     registries already have. Byte-identical files are skipped and the run
     continues. If any differ (the build is not guaranteed to be
     reproducible: build tools are resolved at build time), the plan fails
     closed and that version cannot be finished.
4. In that case release the next patch version through the normal process.
   Yank (PyPI) or deprecate (npm) the incomplete version only if users could
   install a broken combination; a PyPI release without its npm counterpart is
   valid on its own.

Notes:

- The registries' JSON may lag a few minutes behind an upload, so a re-run that
  comes too early may try to upload a file that is in fact already there. PyPI
  and TestPyPI accept an upload of a byte-identical file (same name, same
  hashes) as a no-op and reject one with other bytes ("File already exists";
  `_is_duplicate_file` in pypi/warehouse `warehouse/forklift/legacy.py`, checked
  2026-10-28); the post-upload check then confirms the hashes. npm rejects any
  publish of a version it already has, identical or not, so the npm job fails
  without changing anything: wait and re-run it again.
- **PyPI**: *yank* rather than delete (deleted file names can never be reused);
  installs that pin the version still work, new resolutions skip it. A re-run
  never completes a yanked version: the PyPI/TestPyPI jobs refuse it, and so
  does the npm job, which checks PyPI right before publishing.
- **npm**: deprecate rather than unpublish. Unpublishing is restricted by npm's
  unpublish policy, an unpublished version can never be reused, and the
  preflight refuses it from then on.

## Limitations that need a real GitHub run (not provable locally)

- **Environment checks** read `GET /repos/{repo}/environments/{name}` with the
  job token and `actions: read`. If GitHub refuses that token, `verify` fails
  closed ("cannot read environment"); then the settings must be verified by
  hand before each release and the check adjusted (for example a read-only
  token) - never removed.
- **arm64 Linux runners** (`ubuntu-24.04-arm`, used by the PyTorch end-to-end
  job): free only for public repositories. If unavailable, CI and therefore the
  release cannot complete until the matrix entry or runner is changed.
- **PyPI trusted publishing** for `ragkit-dev`: the pending publisher is
  confirmed only by the first release's upload (TestPyPI's by the rehearsal).
- **npm trusted publishing (OIDC)** with `setup-node`'s `registry-url` and
  `npm publish --ignore-scripts`: confirmed only by the first real release
  (rehearsals never publish to npm); if it fails, nothing is published to npm
  (PyPI has already been released and stays valid; see the table above).
- Whether GitHub rejects `stage` values outside the two choices is not relied
  on: `verify` refuses anything else.

## What CI never does

No CI or release job has an API key: none is defined, and a guard step fails
the job if `GOOGLE_API_KEY` is set. No job calls Gemini, ingests a document,
or downloads an embedding model (`HF_HOME` is a temporary folder with
`HF_HUB_OFFLINE=1`; the PyTorch jobs check it is still empty).
