import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { after, test } from "node:test";

import { main } from "../lib/cli.js";

const work = await mkdtemp(path.join(tmpdir(), "rag-kit-dev-cli-"));
after(() => rm(work, { recursive: true, force: true }));

const SECRET = "secret-value-never-printed";

function sink() {
  const stream = new PassThrough();
  let text = "";
  stream.on("data", (chunk) => { text += chunk; });
  return { stream, text: () => text };
}

// A fake process runner: Python 3.11 on `py -3.11`, uv present, installs succeed
// unless `failOn` matches the step's arguments.
function fakeRun({ failOn = null, uv = true, python = "3.11.9" } = {}) {
  const calls = [];
  const run = async (command, args, options = {}) => {
    calls.push({ command, args, cwd: options.cwd, env: options.env });
    if (command === "uv" && args[0] === "--version") return { code: uv ? 0 : null, stdout: "uv 0.11" };
    if (args.includes("-c")) {
      if (!python || (command === "py" && args[0] !== "-3.11")) return { code: null, stdout: "" };
      return { code: 0, stdout: JSON.stringify({ version: python, executable: "C:\\Py311\\python.exe" }) };
    }
    if (failOn && args.join(" ").includes(failOn)) return { code: 1 };
    return { code: 0 };
  };
  return { run, calls };
}

async function generate(argv, { run = fakeRun().run, interactive = false, platform = "win32" } = {}) {
  const out = sink();
  const err = sink();
  const code = await main(argv, {
    platform, cwd: work, env: { PATH: "x", GOOGLE_API_KEY: SECRET }, stdin: new PassThrough(),
    stdout: out.stream, stderr: err.stream, interactive, run,
  });
  return { code, out: out.text(), err: err.text() };
}

const exists = (p) => stat(p).then(() => true, () => false);

test("--help and --version", async () => {
  assert.equal((await generate(["--help"])).code, 0);
  const version = await generate(["--version"]);
  assert.equal(version.code, 0);
  const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(version.out.trim(), pkg.version);
});

test("usage and validation errors exit 2 and create nothing", async () => {
  for (const argv of [[], ["--embeddings", "openai", "x1"], ["../escape", "--embeddings", "local"],
    ["CON", "--embeddings", "local"], ["fine-name"]]) {
    const before = await readdir(work);
    const result = await generate(argv);
    assert.equal(result.code, 2, JSON.stringify(argv));
    assert.deepEqual(await readdir(work), before, JSON.stringify(argv));
  }
});

test("non-interactive without --embeddings explains the choice and creates nothing", async () => {
  const result = await generate(["needs-choice"]);
  assert.equal(result.code, 2);
  assert.match(result.err, /--embeddings local or --embeddings gemini/);
  assert.equal(await exists(path.join(work, "needs-choice")), false);
});

test("a legacy rag-kit --package-spec exits 2, names ragkit-dev and creates nothing", async () => {
  const { run, calls } = fakeRun();
  const result = await generate(["legacy-spec", "--embeddings", "gemini", "--package-spec", "rag-kit==0.1.0rc1"],
    { run });
  assert.equal(result.code, 2);
  assert.match(result.err, /use "ragkit-dev==0\.1\.0rc1"/);
  assert.deepEqual(calls, []);
  assert.equal(await exists(path.join(work, "legacy-spec")), false);
});

test("a non-empty target folder is left untouched", async () => {
  const target = path.join(work, "occupied");
  await mkdir(target);
  await writeFile(path.join(target, "notes.txt"), "user data");
  const result = await generate(["occupied", "--embeddings", "local", "--no-install"]);
  assert.equal(result.code, 2);
  assert.deepEqual(await readdir(target), ["notes.txt"]);
});

test("--no-install writes the project, runs nothing, creates no .env", async () => {
  const { run, calls } = fakeRun();
  const result = await generate(["only-files", "--embeddings", "gemini", "--no-install"], { run });
  assert.equal(result.code, 0, result.err);
  assert.deepEqual(calls, []);
  const target = path.join(work, "only-files");
  assert.equal(await exists(path.join(target, ".env")), false);
  assert.equal(await exists(path.join(target, ".venv")), false);
  assert.match(await readFile(path.join(target, ".env.example"), "utf8"), /^GOOGLE_API_KEY=$/m);
  assert.match(result.out, /Skipped installation/);
  assert.match(result.out, /Copy-Item \.env\.example \.env/);
  assert.match(result.out, /py -3\.11 -m venv \.venv/);
  assert.match(result.out, /Embeddings: gemini/);
  assert.match(result.out, /GOOGLE_API_KEY with embedding quota/);
});

test("install: python and uv are found first, then files, then the steps in the project folder", async () => {
  const { run, calls } = fakeRun();
  const result = await generate(["installed", "--embeddings", "local"], { run });
  assert.equal(result.code, 0, result.err);
  const target = path.join(work, "installed");
  const steps = calls.filter((c) => c.cwd === target).map((c) => [c.command, ...c.args].join(" "));
  assert.deepEqual(steps, [
    "uv venv .venv --python C:\\Py311\\python.exe",
    "uv pip install --python .venv\\Scripts\\python.exe -r requirements.txt",
  ]);
  assert.ok(calls.filter((c) => c.cwd === target).every((c) => c.env.UV_PYTHON_DOWNLOADS === "never"));
  assert.match(result.out, /about 2\.3 GB/);
  assert.match(result.out, /Next steps:/);
  assert.equal(await exists(path.join(target, ".env")), false);
});

test("--no-uv uses pip from the new venv", async () => {
  const { run, calls } = fakeRun();
  const result = await generate(["with-pip", "--embeddings", "gemini", "--no-uv"], { run });
  assert.equal(result.code, 0, result.err);
  assert.ok(!calls.some((c) => c.command === "uv"));
  assert.ok(calls.some((c) => c.args.join(" ") === "-m venv .venv"));
});

test("uv missing falls back to pip and says so", async () => {
  const result = await generate(["no-uv-here", "--embeddings", "gemini"], { run: fakeRun({ uv: false }).run });
  assert.equal(result.code, 0, result.err);
  assert.match(result.out, /Installer: pip \(uv not found\)/);
});

test("no Python 3.11/3.12: exit 1 and nothing is created", async () => {
  const result = await generate(["no-python", "--embeddings", "local"], { run: fakeRun({ python: null }).run });
  assert.equal(result.code, 1);
  assert.match(result.err, /No Python 3\.11 or 3\.12 interpreter was found/);
  assert.match(result.err, /Nothing was created/);
  assert.equal(await exists(path.join(work, "no-python")), false);
});

test("a failed install keeps everything and prints the exact retry commands", async () => {
  const result = await generate(["half-done", "--embeddings", "local"], {
    run: fakeRun({ failOn: "-r requirements.txt" }).run });
  assert.equal(result.code, 1);
  const target = path.join(work, "half-done");
  assert.equal(await exists(path.join(target, "rag-kit.toml")), true);
  assert.match(result.err, /"Install rag-kit \(requirements\.txt\)" failed/);
  assert.match(result.out, /were kept, and these steps finished: Create \.venv \(uv\)/);
  const retry = result.out.slice(result.out.indexOf("To finish"));
  assert.match(retry, /uv pip install --python \.venv\\Scripts\\python\.exe -r requirements\.txt/);
  assert.doesNotMatch(retry, /uv venv/);  // finished steps are not repeated in the retry list
});

test("linux local installs CPU-only torch first; --gpu skips it", async () => {
  const cpu = fakeRun();
  assert.equal((await generate(["linux-cpu", "--embeddings", "local"], { run: cpu.run, platform: "linux" })).code, 0);
  assert.ok(cpu.calls.some((c) => c.args.includes("https://download.pytorch.org/whl/cpu")));
  const gpu = fakeRun();
  assert.equal((await generate(["linux-gpu", "--embeddings", "local", "--gpu"], { run: gpu.run, platform: "linux" })).code, 0);
  assert.ok(!gpu.calls.some((c) => c.args.includes("https://download.pytorch.org/whl/cpu")));
});

test("--package-spec installs the given wheel and notes the pin", async () => {
  const { run, calls } = fakeRun();
  const result = await generate(["from-wheel", "--embeddings", "gemini", "--package-spec", "C:\\dist\\rag_kit.whl"], { run });
  assert.equal(result.code, 0, result.err);
  assert.ok(calls.some((c) => c.args.join(" ").endsWith("C:\\dist\\rag_kit.whl[gemini]")));
  assert.match(result.out, /requirements\.txt pins ragkit-dev\[gemini\]==0\.1\.0/);
});

test("a relative --package-spec path is taken from the folder the command runs in", async () => {
  const platform = process.platform === "win32" ? "win32" : "linux";
  const { run, calls } = fakeRun();
  const result = await generate(["relative-wheel", "--embeddings", "gemini", "--package-spec",
    "dist/ragkit_dev-0.1.0-py3-none-any.whl"], { run, platform });
  assert.equal(result.code, 0, result.err);
  const install = calls.find((c) => c.args.at(-1).endsWith("[gemini]"));
  assert.equal(install.args.at(-1), `${path.resolve(work, "dist", "ragkit_dev-0.1.0-py3-none-any.whl")}[gemini]`);
  assert.equal(install.cwd, path.join(work, "relative-wheel"));
});

test("environment values, such as API keys, are never printed", async () => {
  for (const argv of [["quiet-1", "--embeddings", "local"], ["quiet-2", "--embeddings", "gemini", "--no-install"]]) {
    const result = await generate(argv);
    assert.ok(!result.out.includes(SECRET) && !result.err.includes(SECRET), argv.join(" "));
  }
});
