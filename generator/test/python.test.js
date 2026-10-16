import assert from "node:assert/strict";
import { test } from "node:test";

import { candidates, findPython, PythonNotFoundError } from "../lib/python.js";

// A fake process runner: maps "command args..." to an interpreter version, a
// failure (the Windows Store python3 stub exits 9009), or "missing" (ENOENT).
function fakeRun(table) {
  const calls = [];
  const run = async (command, args) => {
    const key = [command, ...args.slice(0, args.indexOf("-c"))].join(" ");
    calls.push(key);
    const entry = table[key];
    if (entry === undefined || entry === "missing") {
      return { code: null, stdout: "", error: Object.assign(new Error("spawn ENOENT"), { code: "ENOENT" }) };
    }
    if (typeof entry === "number") return { code: entry, stdout: "" };
    return { code: 0, stdout: `${JSON.stringify({ version: entry, executable: `/py/${entry}` })}\n` };
  };
  return { run, calls };
}

test("candidate order: 3.11 first, then 3.12, then generic names", () => {
  assert.deepEqual(candidates("win32").map((c) => [c.command, ...c.args].join(" ")),
    ["py -3.11", "py -3.12", "python", "python3"]);
  assert.deepEqual(candidates("linux").map((c) => c.command),
    ["python3.11", "python3.12", "python3", "python"]);
  assert.deepEqual(candidates("darwin").map((c) => c.command),
    ["python3.11", "python3.12", "python3", "python"]);
  assert.deepEqual(candidates("linux", "/opt/py/bin/python"), [{ command: "/opt/py/bin/python", args: [] }]);
});

test("prefers 3.11 when both are installed", async () => {
  const { run } = fakeRun({ "py -3.11": "3.11.9", "py -3.12": "3.12.7" });
  const found = await findPython({ platform: "win32", run });
  assert.deepEqual(found, { executable: "/py/3.11.9", version: "3.11.9", label: "py -3.11" });
});

test("falls back to 3.12", async () => {
  const { run } = fakeRun({ "python3.12": "3.12.7", python3: "3.13.1" });
  assert.equal((await findPython({ platform: "linux", run })).version, "3.12.7");
});

test("skips unsupported versions, missing commands and the Windows Store stub", async () => {
  const { run, calls } = fakeRun({ "py -3.11": "missing", "py -3.12": 103, python: "3.10.11", python3: 9009 });
  await assert.rejects(findPython({ platform: "win32", run }), (error) => {
    assert.ok(error instanceof PythonNotFoundError);
    assert.match(error.message, /No Python 3\.11 or 3\.12 interpreter was found/);
    assert.match(error.message, /python: Python 3\.10\.11 \(rag-kit needs 3\.11 or 3\.12\)/);
    assert.match(error.message, /python3: not available/);
    assert.match(error.message, /--python PATH/);
    assert.match(error.message, /--no-install/);
    return true;
  });
  assert.deepEqual(calls, ["py -3.11", "py -3.12", "python", "python3"]);
});

test("an explicit --python must be 3.11 or 3.12", async () => {
  const ok = fakeRun({ "C:\\Py312\\python.exe": "3.12.1" });
  assert.equal((await findPython({ platform: "win32", explicit: "C:\\Py312\\python.exe", run: ok.run })).version,
    "3.12.1");
  const bad = fakeRun({ "/usr/bin/python3": "3.13.0" });
  await assert.rejects(findPython({ platform: "linux", explicit: "/usr/bin/python3", run: bad.run }),
    /--python \/usr\/bin\/python3 is not a Python 3\.11 or 3\.12 interpreter/);
  assert.deepEqual(bad.calls, ["/usr/bin/python3"]);
});

test("garbage output is treated as not available", async () => {
  const run = async () => ({ code: 0, stdout: "not json" });
  await assert.rejects(findPython({ platform: "linux", run }), PythonNotFoundError);
});
