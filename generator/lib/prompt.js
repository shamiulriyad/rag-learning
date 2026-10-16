// The embedding choice, with what each option costs, shown before anything is installed.

import { createInterface } from "node:readline/promises";

import { UsageError } from "./args.js";

export class CancelledError extends Error {}

export function disclosure(choice, { platform, gpu }) {
  const local = [
    "Local BGE-M3 (EMBEDDING_PROVIDER=huggingface, model BAAI/bge-m3)",
    "  - Embeddings are computed on this computer; no API key is needed for them.",
    platform === "linux"
      ? gpu
        ? "  - Installs PyTorch with CUDA (--gpu) and sentence-transformers: several GB."
        : "  - Installs CPU-only PyTorch and sentence-transformers: about 1 GB on disk (measured on Windows)."
      : "  - Installs PyTorch and sentence-transformers: about 1 GB on disk (measured on Windows).",
    "    Actual disk use varies by platform and dependency versions.",
    "  - The BGE-M3 model (about 2.3 GB) is downloaded separately into the Hugging Face",
    "    cache the first time you ingest a document - not during this setup.",
  ];
  const gemini = [
    "Gemini (EMBEDDING_PROVIDER=google, model models/gemini-embedding-001)",
    "  - Small install; no model download.",
    "  - Needs a GOOGLE_API_KEY with embedding quota. On the free tier rag-kit pauses",
    "    60 s between batches (EMBED_SLEEP), so large documents ingest slowly.",
    "  - Document text is sent to Google's API.",
  ];
  const both = [
    "Either way: answers (rag-kit ask / serve) use Gemini and need GOOGLE_API_KEY;",
    "the question and the retrieved passages are sent to Google to write the answer.",
    "You add the key to .env yourself; rag-kit-dev never asks for it.",
    "A collection built with one provider cannot be searched with the other.",
  ];
  if (choice === "local") return [...local, "", ...both].join("\n");
  if (choice === "gemini") return [...gemini, "", ...both].join("\n");
  return ["  1) " + local[0], ...local.slice(1).map((l) => "   " + l), "",
    "  2) " + gemini[0], ...gemini.slice(1).map((l) => "   " + l), "", ...both].join("\n");
}

const ANSWERS = { 1: "local", local: "local", 2: "gemini", gemini: "gemini" };

// Returns "local" or "gemini". Asks only in an interactive terminal; there is no default.
export async function chooseEmbeddings(options, { interactive, input, output, platform }) {
  if (options.embeddings) {
    return options.embeddings;
  }
  if (!interactive || options.yes) {
    throw new UsageError(
      "Choose how the project creates embeddings: add --embeddings local or --embeddings gemini " +
        "(required when not running in an interactive terminal or with --yes).",
    );
  }
  output.write(`\nHow should this project create embeddings?\n\n${disclosure(null, { platform, gpu: options.gpu })}\n\n`);
  const rl = createInterface({ input, output, terminal: false });
  // End of input (Ctrl+D / Ctrl+Z, a closed pipe) must cancel, not hang.
  const ended = new AbortController();
  rl.on("close", () => ended.abort());
  try {
    for (;;) {
      let answer;
      try {
        answer = (await rl.question("Type 1 (local) or 2 (gemini): ", { signal: ended.signal }))
          .trim().toLowerCase();
      } catch {
        throw new CancelledError("Cancelled: no embedding choice was made.");
      }
      if (ANSWERS[answer]) return ANSWERS[answer];
      output.write(`"${answer}" is not 1 or 2.\n`);
    }
  } finally {
    rl.close();
  }
}
