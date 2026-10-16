import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, test } from "node:test";

import { render, scaffold, TEMPLATE_DIR, templateValues } from "../lib/scaffold.js";

const work = await mkdtemp(path.join(tmpdir(), "rag-kit-dev-scaffold-"));
after(() => rm(work, { recursive: true, force: true }));

const EXPECTED_FILES = [".env.example", ".gitignore", "README.md", "data/.gitkeep", "example.py",
  "rag-kit.toml", "requirements.txt"];

async function create(name, embeddings) {
  const target = path.join(work, name);
  const files = await scaffold({ target, values: templateValues({ name, embeddings, version: "0.1.0" }) });
  const read = (rel) => readFile(path.join(target, rel), "utf8");
  return { target, files, read };
}

test("writes exactly the project files, never .env", async () => {
  const { target, files } = await create("files-local", "local");
  assert.deepEqual(files, EXPECTED_FILES);
  assert.deepEqual((await readdir(target)).sort(), [".env.example", ".gitignore", "README.md", "data", "example.py",
    "rag-kit.toml", "requirements.txt"]);
});

test("local: .env.example has an empty key and the local provider", async () => {
  const { read } = await create("env-local", "local");
  const env = await read(".env.example");
  assert.match(env, /^GOOGLE_API_KEY=$/m);
  assert.match(env, /^EMBEDDING_PROVIDER=huggingface$/m);
  assert.match(env, /^EMBEDDING_MODEL=BAAI\/bge-m3$/m);
  assert.match(env, /^QDRANT_PATH=qdrant_data$/m);
  assert.match(env, /^COLLECTION_NAME=pdf_rag$/m);  // the runtime default, unchanged
  assert.doesNotMatch(env, /^EMBED_SLEEP=/m);
  assert.equal(await read("requirements.txt"),
    "# This project's Python dependencies (installed into .venv by rag-kit-dev).\nrag-kit[local,gemini]==0.1.0\n");
});

test("gemini: provider, model and batch pause", async () => {
  const { read } = await create("env-gemini", "gemini");
  const env = await read(".env.example");
  assert.match(env, /^GOOGLE_API_KEY=$/m);
  assert.match(env, /^EMBEDDING_PROVIDER=google$/m);
  assert.match(env, /^EMBEDDING_MODEL=models\/gemini-embedding-001$/m);
  assert.match(env, /^EMBED_SLEEP=60$/m);
  assert.match(await read("requirements.txt"), /^rag-kit\[gemini\]==0\.1\.0$/m);
  assert.doesNotMatch(await read("README.md"), /torch/);
});

test("every key-like line in .env.example is empty", async () => {
  for (const embeddings of ["local", "gemini"]) {
    const env = await (await create(`keys-${embeddings}`, embeddings)).read(".env.example");
    for (const line of env.split("\n").filter((l) => /^[A-Z_]*(KEY|TOKEN|SECRET)[A-Z_]*=/.test(l))) {
      assert.match(line, /=$/, line);
    }
  }
});

test(".gitignore keeps secrets and local data out of git", async () => {
  const ignore = await (await create("ignore", "local")).read(".gitignore");
  for (const entry of [".env", "qdrant_data/", "uploads/", ".venv/", "!.env.example"]) {
    assert.ok(ignore.split("\n").includes(entry), entry);
  }
});

test("all placeholders are filled", async () => {
  const { target, files } = await create("placeholders", "local");
  for (const rel of files) {
    assert.doesNotMatch(await readFile(path.join(target, rel), "utf8"), /\{\{|\}\}/, rel);
  }
});

test("unknown placeholders fail loudly", () => {
  assert.throws(() => render("{{NOPE}}", {}, "x"), /unknown placeholder \{\{NOPE\}\}/);
});

test("never overwrites an existing file", async () => {
  const target = path.join(work, "existing");
  await mkdir(target);
  await writeFile(path.join(target, "README.md"), "mine");
  await assert.rejects(
    scaffold({ target, values: templateValues({ name: "existing", embeddings: "local", version: "0.1.0" }) }),
    { code: "EEXIST" });
  assert.equal(await readFile(path.join(target, "README.md"), "utf8"), "mine");
});

test("refuses a template that would produce .env", async () => {
  const templates = path.join(work, "bad-templates");
  await mkdir(templates);
  await writeFile(path.join(templates, ".env"), "GOOGLE_API_KEY=");
  await assert.rejects(scaffold({ target: path.join(work, "bad"), values: {}, templateDir: templates }),
    /Refusing to write \.env/);
});

test("the shipped template folder contains no .env", async () => {
  const names = await readdir(TEMPLATE_DIR, { recursive: true });
  assert.ok(!names.some((n) => path.basename(n) === ".env"), names.join(", "));
});
