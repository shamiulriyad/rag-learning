import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, test } from "node:test";

import { checkTarget, resolveTarget, validateName, ValidationError } from "../lib/validate.js";

const work = await mkdtemp(path.join(tmpdir(), "rag-kit-dev-validate-"));
after(() => rm(work, { recursive: true, force: true }));

test("valid names", () => {
  for (const name of ["my-rag", "rag_2", "Docs.Search", "a", "x".repeat(214)]) {
    assert.equal(validateName(name), name);
  }
});

test("invalid names are rejected with a reason", () => {
  const cases = {
    ".": /creates a new folder/,
    "..": /creates a new folder/,
    "../escape": /looks like a path/,
    "a/b": /looks like a path/,
    "a\\b": /looks like a path/,
    "C:evil": /looks like a path/,
    "-flag": /not a valid project name/,
    ".hidden": /not a valid project name/,
    "has space": /not a valid project name/,
    "": /not a valid project name/,
    ["x".repeat(215)]: /not a valid project name/,
    "trailing.": /ends with "."/,
    "CON": /reserved device name/,
    "nul.txt": /reserved device name/,
    "com1": /reserved device name/,
    "LPT9.md": /reserved device name/,
  };
  for (const [name, message] of Object.entries(cases)) {
    assert.throws(() => validateName(name), (error) => error instanceof ValidationError && message.test(error.message),
      `name ${JSON.stringify(name)}`);
  }
});

test("names similar to reserved ones are allowed", () => {
  for (const name of ["console", "nul-rag", "com10", "auxiliary"]) {
    assert.equal(validateName(name), name);
  }
});

test("the target is always a direct child of the working directory", () => {
  assert.equal(resolveTarget("my-rag", work), path.join(work, "my-rag"));
  assert.throws(() => resolveTarget("../outside", work), ValidationError);
  assert.throws(() => resolveTarget("a/b", work), ValidationError);
});

test("a missing or empty folder is accepted, nothing is created", async () => {
  const missing = path.join(work, "missing");
  assert.deepEqual(await checkTarget(missing), { exists: false });
  await assert.rejects(readdir(missing), { code: "ENOENT" });

  const empty = path.join(work, "empty");
  await mkdir(empty);
  assert.deepEqual(await checkTarget(empty), { exists: true });
});

test("a non-empty folder or a file is refused", async () => {
  const full = path.join(work, "full");
  await mkdir(full);
  await writeFile(path.join(full, "keep.txt"), "user data");
  await assert.rejects(checkTarget(full), /already exists and is not empty/);
  assert.deepEqual(await readdir(full), ["keep.txt"]);

  const file = path.join(work, "a-file");
  await writeFile(file, "x");
  await assert.rejects(checkTarget(file), /is not a folder/);
});
