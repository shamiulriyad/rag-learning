import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";

import {
  CPU_TORCH_INDEX, installEnv, installPlan, legacyPackageSpecError, packageSpecWithExtras, pinnedRequirement,
  runSteps, TEST_PYPI_INDEX, venvPython,
} from "../lib/install.js";

const BASE = { pythonExecutable: "/usr/bin/python3.11", gpu: false, packageSpec: undefined, testPypi: false,
  version: "0.1.0" };

const plan = (overrides) => installPlan({ ...BASE, ...overrides })
  .map((step) => [step.command, ...step.args].join(" "));

test("requirements.txt pins the published release with the right extras", () => {
  assert.equal(pinnedRequirement("local", "0.1.0"), "ragkit-dev[local,gemini]==0.1.0");
  assert.equal(pinnedRequirement("gemini", "0.1.0"), "ragkit-dev[gemini]==0.1.0");
});

test("--package-spec gets the extras for wheels, sdists, folders and requirement strings", () => {
  assert.equal(packageSpecWithExtras("C:\\dist\\ragkit_dev-0.1.0-py3-none-any.whl", "local"),
    "C:\\dist\\ragkit_dev-0.1.0-py3-none-any.whl[local,gemini]");
  assert.equal(packageSpecWithExtras("../ragkit_dev-0.1.0.tar.gz", "gemini"), "../ragkit_dev-0.1.0.tar.gz[gemini]");
  assert.equal(packageSpecWithExtras("ragkit-dev==0.1.0rc1", "gemini"), "ragkit-dev[gemini]==0.1.0rc1");
  assert.equal(packageSpecWithExtras("ragkit_dev[api] >= 0.1", "local"), "ragkit-dev[local,gemini]>= 0.1");
  assert.equal(packageSpecWithExtras("ragkit-dev", "gemini"), "ragkit-dev[gemini]");
});

test("--package-spec accepts repeated separators in ragkit-dev", () => {
  assert.equal(packageSpecWithExtras("ragkit--dev==0.1.0", "gemini"), "ragkit-dev[gemini]==0.1.0");
  assert.equal(packageSpecWithExtras("ragkit__dev==0.1.0", "gemini"), "ragkit-dev[gemini]==0.1.0");
  assert.equal(packageSpecWithExtras("ragkit..dev", "local"), "ragkit-dev[local,gemini]");
});

test("a legacy rag-kit requirement is refused, never turned into a malformed spec", () => {
  for (const spec of ["rag-kit==0.1.0rc1", "rag_kit[api] >= 0.1", " RAG.KIT ", "rag--kit", "rag-kit; python_version>'3'"]) {
    assert.match(legacyPackageSpecError(spec), /the Python distribution is ragkit-dev, not rag-kit; use "ragkit-dev/, spec);
    assert.throws(() => packageSpecWithExtras(spec, "gemini"), /ragkit-dev, not rag-kit/, spec);
  }
  assert.match(legacyPackageSpecError("rag-kit==0.1.0rc1"), /use "ragkit-dev==0\.1\.0rc1"\.$/);
  // File names that start with the old name are still files, not requirements.
  for (const file of ["rag_kit-0.1.0-py3-none-any.whl", "rag-kit-0.1.0.tar.gz", "C:\\dist\\rag_kit.whl"]) {
    assert.equal(legacyPackageSpecError(file), null, file);
    assert.equal(packageSpecWithExtras(file, "gemini"), `${file}[gemini]`);
  }
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
    packageSpec: "C:\\dist\\ragkit_dev-0.1.0-py3-none-any.whl" }), [
    "uv venv .venv --python C:\\py.exe",
    "uv pip install --python .venv\\Scripts\\python.exe C:\\dist\\ragkit_dev-0.1.0-py3-none-any.whl[gemini]",
  ]);
});

test("--test-pypi takes only rag-kit from TestPyPI, without dependencies", () => {
  const steps = plan({ platform: "linux", useUv: false, embeddings: "gemini", testPypi: true });
  assert.deepEqual(steps.slice(1), [
    `.venv/bin/python -m pip install --disable-pip-version-check --no-deps --index-url ${TEST_PYPI_INDEX} ragkit-dev==0.1.0`,
    ".venv/bin/python -m pip install --disable-pip-version-check ragkit-dev[gemini]==0.1.0",
  ]);
  const rc = plan({ platform: "linux", useUv: true, embeddings: "local", testPypi: true,
    packageSpec: "ragkit-dev==0.1.0rc1" });
  assert.ok(rc.includes(`uv pip install --python .venv/bin/python --no-deps --index-url ${TEST_PYPI_INDEX} ragkit-dev==0.1.0rc1`));
  assert.ok(rc.includes("uv pip install --python .venv/bin/python ragkit-dev[local,gemini]==0.1.0rc1"));
  // TestPyPI is never an extra index for the dependency install.
  assert.equal(rc.filter((s) => s.includes(TEST_PYPI_INDEX)).length, 1);
});

test("uv may never download its own Python", () => {
  assert.equal(installEnv({ PATH: "x" }).UV_PYTHON_DOWNLOADS, "never");
  assert.equal(installEnv({ PATH: "x" }).PATH, "x");
});

test("runSteps runs the project's .venv python by absolute path; PATH commands stay as they are", async () => {
  const steps = installPlan({ ...BASE, platform: process.platform === "win32" ? "win32" : "linux",
    useUv: false, embeddings: "gemini" });
  const ran = [];
  const run = async (command) => { ran.push(command); return { code: 0 }; };
  const cwd = path.resolve("project-folder");
  await runSteps([...steps, { label: "uv", command: "uv", args: [] }], { cwd, env: {}, run, log: () => {} });
  assert.equal(ran[0], "/usr/bin/python3.11");                 // already absolute
  assert.equal(ran[1], path.resolve(cwd, venvPython(process.platform === "win32" ? "win32" : "linux")));
  assert.ok(path.isAbsolute(ran[1]));
  assert.equal(ran[2], "uv");                                   // found on PATH
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
