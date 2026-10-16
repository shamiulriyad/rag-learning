import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CPU_TORCH_INDEX, installEnv, installPlan, packageSpecWithExtras, pinnedRequirement, runSteps, TEST_PYPI_INDEX,
} from "../lib/install.js";

const BASE = { pythonExecutable: "/usr/bin/python3.11", gpu: false, packageSpec: undefined, testPypi: false,
  version: "0.1.0" };

const plan = (overrides) => installPlan({ ...BASE, ...overrides })
  .map((step) => [step.command, ...step.args].join(" "));

test("requirements.txt pins the published release with the right extras", () => {
  assert.equal(pinnedRequirement("local", "0.1.0"), "rag-kit[local,gemini]==0.1.0");
  assert.equal(pinnedRequirement("gemini", "0.1.0"), "rag-kit[gemini]==0.1.0");
});

test("--package-spec gets the extras for wheels, sdists, folders and requirement strings", () => {
  assert.equal(packageSpecWithExtras("C:\\dist\\rag_kit-0.1.0-py3-none-any.whl", "local"),
    "C:\\dist\\rag_kit-0.1.0-py3-none-any.whl[local,gemini]");
  assert.equal(packageSpecWithExtras("../rag_kit-0.1.0.tar.gz", "gemini"), "../rag_kit-0.1.0.tar.gz[gemini]");
  assert.equal(packageSpecWithExtras("rag-kit==0.1.0rc1", "gemini"), "rag-kit[gemini]==0.1.0rc1");
  assert.equal(packageSpecWithExtras("rag_kit[api] >= 0.1", "local"), "rag-kit[local,gemini]>= 0.1");
  assert.equal(packageSpecWithExtras("rag-kit", "gemini"), "rag-kit[gemini]");
});

test("linux + local + uv: CPU-only torch first, then requirements.txt", () => {
  assert.deepEqual(plan({ platform: "linux", useUv: true, embeddings: "local" }), [
    "uv venv .venv --python /usr/bin/python3.11",
    `uv pip install --python .venv/bin/python torch --index-url ${CPU_TORCH_INDEX}`,
    "uv pip install --python .venv/bin/python -r requirements.txt",
  ]);
});

test("linux + local + pip, never upgrading pip", () => {
  assert.deepEqual(plan({ platform: "linux", useUv: false, embeddings: "local" }), [
    "/usr/bin/python3.11 -m venv .venv",
    `.venv/bin/python -m pip install --disable-pip-version-check torch --index-url ${CPU_TORCH_INDEX}`,
    ".venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt",
  ]);
  assert.ok(plan({ platform: "linux", useUv: false, embeddings: "local" }).every((s) => !/--upgrade|-U\b/.test(s)));
});

test("--gpu, Gemini and non-Linux platforms skip the CPU torch step", () => {
  for (const overrides of [
    { platform: "linux", embeddings: "local", gpu: true },
    { platform: "linux", embeddings: "gemini" },
    { platform: "win32", embeddings: "local", pythonExecutable: "C:\\Py311\\python.exe" },
    { platform: "darwin", embeddings: "local" },
  ]) {
    for (const useUv of [true, false]) {
      assert.ok(plan({ ...overrides, useUv }).every((step) => !step.includes(CPU_TORCH_INDEX)),
        JSON.stringify({ ...overrides, useUv }));
    }
  }
});

test("windows paths", () => {
  assert.deepEqual(plan({ platform: "win32", useUv: false, embeddings: "gemini",
    pythonExecutable: "C:\\Py311\\python.exe" }), [
    "C:\\Py311\\python.exe -m venv .venv",
    ".venv\\Scripts\\python.exe -m pip install --disable-pip-version-check -r requirements.txt",
  ]);
  assert.deepEqual(plan({ platform: "win32", useUv: true, embeddings: "local",
    pythonExecutable: "C:\\Py311\\python.exe" }), [
    "uv venv .venv --python C:\\Py311\\python.exe",
    "uv pip install --python .venv\\Scripts\\python.exe -r requirements.txt",
  ]);
});

test("--package-spec installs the given package instead of requirements.txt", () => {
  assert.deepEqual(plan({ platform: "win32", useUv: true, embeddings: "gemini", pythonExecutable: "C:\\py.exe",
    packageSpec: "C:\\dist\\rag_kit-0.1.0-py3-none-any.whl" }), [
    "uv venv .venv --python C:\\py.exe",
    "uv pip install --python .venv\\Scripts\\python.exe C:\\dist\\rag_kit-0.1.0-py3-none-any.whl[gemini]",
  ]);
});

test("--test-pypi takes only rag-kit from TestPyPI, without dependencies", () => {
  const steps = plan({ platform: "linux", useUv: false, embeddings: "gemini", testPypi: true });
  assert.deepEqual(steps.slice(1), [
    `.venv/bin/python -m pip install --disable-pip-version-check --no-deps --index-url ${TEST_PYPI_INDEX} rag-kit==0.1.0`,
    ".venv/bin/python -m pip install --disable-pip-version-check rag-kit[gemini]==0.1.0",
  ]);
  const rc = plan({ platform: "linux", useUv: true, embeddings: "local", testPypi: true,
    packageSpec: "rag-kit==0.1.0rc1" });
  assert.ok(rc.includes(`uv pip install --python .venv/bin/python --no-deps --index-url ${TEST_PYPI_INDEX} rag-kit==0.1.0rc1`));
  assert.ok(rc.includes("uv pip install --python .venv/bin/python rag-kit[local,gemini]==0.1.0rc1"));
  // TestPyPI is never an extra index for the dependency install.
  assert.equal(rc.filter((s) => s.includes(TEST_PYPI_INDEX)).length, 1);
});

test("uv may never download its own Python", () => {
  assert.equal(installEnv({ PATH: "x" }).UV_PYTHON_DOWNLOADS, "never");
  assert.equal(installEnv({ PATH: "x" }).PATH, "x");
});

test("runSteps stops at the first failure and reports what is left", async () => {
  const steps = [{ label: "a", command: "a", args: [] }, { label: "b", command: "b", args: ["x y"] },
    { label: "c", command: "c", args: [] }];
  const ran = [];
  const logs = [];
  const run = async (command) => { ran.push(command); return { code: command === "b" ? 1 : 0 }; };
  const result = await runSteps(steps, { cwd: ".", env: {}, run, log: (line) => logs.push(line) });
  assert.equal(result.ok, false);
  assert.deepEqual(ran, ["a", "b"]);
  assert.deepEqual(result.completed.map((s) => s.label), ["a"]);
  assert.equal(result.failed.label, "b");
  assert.deepEqual(result.remaining.map((s) => s.label), ["b", "c"]);
  assert.ok(logs.some((line) => line.includes('b "x y"')));
});
