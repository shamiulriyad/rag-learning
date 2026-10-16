import assert from "node:assert/strict";
import { test } from "node:test";

import { parseCliArgs, UsageError } from "../lib/args.js";

test("defaults for a plain project name", () => {
  assert.deepEqual(parseCliArgs(["my-rag"]), {
    help: false,
    version: false,
    name: "my-rag",
    embeddings: undefined,
    gpu: false,
    python: undefined,
    useUv: true,
    install: true,
    yes: false,
    packageSpec: undefined,
    testPypi: false,
  });
});

test("every option is parsed", () => {
  const options = parseCliArgs([
    "my-rag", "--embeddings", "local", "--gpu", "--python", "C:\\Py311\\python.exe", "--no-uv",
    "--no-install", "-y", "--package-spec", "dist/rag_kit-0.1.0-py3-none-any.whl", "--test-pypi",
  ]);
  assert.equal(options.embeddings, "local");
  assert.equal(options.gpu, true);
  assert.equal(options.python, "C:\\Py311\\python.exe");
  assert.equal(options.useUv, false);
  assert.equal(options.install, false);
  assert.equal(options.yes, true);
  assert.equal(options.packageSpec, "dist/rag_kit-0.1.0-py3-none-any.whl");
  assert.equal(options.testPypi, true);
});

test("help and version need no project name", () => {
  assert.equal(parseCliArgs(["--help"]).help, true);
  assert.equal(parseCliArgs(["-h"]).help, true);
  assert.equal(parseCliArgs(["--version"]).version, true);
});

test("usage errors", () => {
  const cases = [
    [[], /Missing the project name/],
    [["a", "b"], /Expected one project name/],
    [["my-rag", "--embeddings", "openai"], /must be "local" or "gemini"/],
    [["my-rag", "--unknown"], /Unknown option/],
    [["my-rag", "--python", " "], /--python needs a value/],
    [["my-rag", "--package-spec", ""], /--package-spec needs a value/],
  ];
  for (const [argv, message] of cases) {
    assert.throws(() => parseCliArgs(argv), (error) => error instanceof UsageError && message.test(error.message),
      `argv ${JSON.stringify(argv)}`);
  }
});
