// The generator installs ragkit-dev==<its own version>, so the two must match.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { RAG_KIT_VERSION } from "../lib/version.js";

const pyproject = new URL("../../pyproject.toml", import.meta.url);

// npm writes a pre-release as 0.1.0-rc.1 where Python writes 0.1.0rc1 (npm_form in
// scripts/check_versions.py); final versions are the same in both. Anything else is
// not a form the release uses, so it maps to null.
const PEP440_LABELS = { alpha: "a", beta: "b", rc: "rc" };
function pep440(npmVersion) {
  const match = npmVersion.match(/^(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?$/);
  if (!match) return null;
  return match[2] ? `${match[1]}${PEP440_LABELS[match[2]]}${match[3]}` : match[1];
}

test("npm versions map to the Python form of the same release", () => {
  assert.equal(pep440("0.1.0"), "0.1.0");
  assert.equal(pep440("0.1.0-rc.1"), "0.1.0rc1");
  assert.equal(pep440("1.2.3-alpha.2"), "1.2.3a2");
  assert.equal(pep440("1.2.3-beta.10"), "1.2.3b10");
  for (const other of ["0.1.0rc1", "0.1.0-rc1", "0.1.0-dev.1", "0.1", "v0.1.0"]) {
    assert.equal(pep440(other), null, other);
  }
});

test("the generator version is the one it pins ragkit-dev to", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(RAG_KIT_VERSION, pkg.version);
});

test("generator/package.json and pyproject.toml have the same version",
  { skip: !existsSync(pyproject) && "pyproject.toml not present (installed package)" }, () => {
    const text = readFileSync(pyproject, "utf8");
    const project = text.split(/^\[project\]\s*$/m)[1].split(/^\[/m)[0];
    const match = project.match(/^version\s*=\s*"([^"]+)"/m);
    assert.ok(match, "no version in [project]");
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    assert.equal(pep440(pkg.version), match[1],
      `package.json ${pkg.version} is not pyproject.toml ${match[1]} in npm form`);
  });
