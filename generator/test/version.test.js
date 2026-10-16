// The generator installs rag-kit==<its own version>, so the two must match.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { RAG_KIT_VERSION } from "../lib/version.js";

const pyproject = new URL("../../pyproject.toml", import.meta.url);

test("the generator version is the one it pins rag-kit to", () => {
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
    assert.equal(pkg.version, match[1]);
  });
