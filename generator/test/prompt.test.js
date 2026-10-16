import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import { test } from "node:test";

import { UsageError } from "../lib/args.js";
import { CancelledError, chooseEmbeddings, disclosure } from "../lib/prompt.js";

// Feeds one answer each time the prompt appears, like a person typing.
function terminal(answers, { endAfter = false } = {}) {
  const input = new PassThrough();
  const output = new PassThrough();
  let text = "";
  output.on("data", (chunk) => {
    text += chunk;
    if (String(chunk).includes("Type 1 (local) or 2 (gemini):")) {
      if (answers.length) setImmediate(() => input.write(`${answers.shift()}\n`));
      else if (endAfter) setImmediate(() => input.end());
    }
  });
  return { input, output, text: () => text };
}

const ask = (options, io) => chooseEmbeddings({ yes: false, gpu: false, ...options },
  { interactive: true, platform: "win32", ...io });

test("both options are explained before asking, and there is no default", async () => {
  const io = terminal(["", "3", "2"]);
  assert.equal(await ask({}, io), "gemini");
  const shown = io.text();
  assert.match(shown, /1\) Local BGE-M3/);
  assert.match(shown, /about 2\.3 GB/);
  assert.match(shown, /not during this setup/);
  assert.match(shown, /2\) Gemini/);
  assert.match(shown, /GOOGLE_API_KEY with embedding quota/);
  assert.match(shown, /never asks for it/);
  assert.match(shown, /"" is not 1 or 2/);
  assert.match(shown, /"3" is not 1 or 2/);
});

test("words work as answers too", async () => {
  assert.equal(await ask({}, terminal(["LOCAL"])), "local");
});

test("end of input cancels instead of hanging", async () => {
  await assert.rejects(ask({}, terminal([], { endAfter: true })), CancelledError);
});

test("an explicit --embeddings is used without asking", async () => {
  const io = terminal([]);
  assert.equal(await ask({ embeddings: "local" }, io), "local");
  assert.equal(io.text(), "");
});

test("non-interactive runs and --yes require --embeddings", async () => {
  for (const [options, interactive] of [[{}, false], [{ yes: true }, true]]) {
    await assert.rejects(
      chooseEmbeddings({ gpu: false, ...options }, { interactive, platform: "linux", input: null, output: null }),
      (error) => error instanceof UsageError && /--embeddings local or --embeddings gemini/.test(error.message));
  }
});

test("the local disclosure matches the platform", () => {
  assert.match(disclosure("local", { platform: "linux", gpu: false }), /CPU-only PyTorch/);
  assert.match(disclosure("local", { platform: "linux", gpu: true }), /PyTorch with CUDA/);
  assert.match(disclosure("local", { platform: "darwin", gpu: false }), /Installs PyTorch and sentence-transformers/);
  assert.doesNotMatch(disclosure("gemini", { platform: "linux", gpu: false }), /PyTorch/);
});
