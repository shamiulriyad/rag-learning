// Writes the project files from templates/default. Never overwrites a file and
// never writes .env.

import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CPU_TORCH_INDEX, pinnedRequirement } from "./install.js";

export const TEMPLATE_DIR = fileURLToPath(new URL("../templates/default/", import.meta.url));

// npm drops or mangles dot-files in packages, so templates use these names.
export const RENAMES = {
  _gitignore: ".gitignore",
  "_env.example": ".env.example",
  _gitkeep: ".gitkeep",
  "requirements.txt.tmpl": "requirements.txt",
};

const EMBEDDINGS = {
  local: {
    label: "local BGE-M3",
    provider: "huggingface",
    model: "BAAI/bge-m3",
    note: "Embeddings are computed on this computer (no key needed for them); the model " +
      "(about 2.3 GB) is downloaded into the Hugging Face cache on the first ingest.",
    geminiNote: "",
    extra: "# Where the local model is cached (default: the Hugging Face cache in your home folder):\n" +
      "# HF_HOME=\n",
  },
  gemini: {
    label: "Gemini",
    provider: "google",
    model: "models/gemini-embedding-001",
    note: "Embeddings come from Google's API and need GOOGLE_API_KEY with embedding quota; " +
      "document text is sent to Google.",
    geminiNote: " and the embeddings",
    extra: "# Seconds to pause between embedding batches (Gemini free tier: about 100 texts/minute):\n" +
      "EMBED_SLEEP=60\n",
  },
};

export function templateValues({ name, embeddings, version }) {
  const choice = EMBEDDINGS[embeddings];
  return {
    PROJECT_NAME: name,
    RAG_KIT_VERSION: version,
    RAG_KIT_REQUIREMENT: pinnedRequirement(embeddings, version),
    EMBEDDINGS_LABEL: choice.label,
    EMBEDDINGS_NOTE: choice.note,
    EMBEDDING_PROVIDER: choice.provider,
    EMBEDDING_MODEL: choice.model,
    EMBEDDING_EXTRA: choice.extra,
    GEMINI_EMBEDDING_NOTE: choice.geminiNote,
    MANUAL_TORCH_STEP: embeddings === "local"
      ? `.venv/bin/python -m pip install torch --index-url ${CPU_TORCH_INDEX}   # Linux only: CPU-only PyTorch\n`
      : "",
  };
}

export function render(text, values, source) {
  const out = text.replace(/\{\{([A-Z_]+)\}\}/g, (match, key) => {
    if (!(key in values)) throw new Error(`Template ${source} uses unknown placeholder ${match}`);
    return values[key];
  });
  if (out.includes("{{")) throw new Error(`Template ${source} has an unfinished placeholder`);
  return out;
}

async function* templateFiles(dir, relative = "") {
  for (const entry of await readdir(path.join(dir, relative), { withFileTypes: true })) {
    const rel = path.join(relative, entry.name);
    if (entry.isDirectory()) yield* templateFiles(dir, rel);
    else yield rel;
  }
}

// Returns the project-relative paths written, sorted.
export async function scaffold({ target, values, templateDir = TEMPLATE_DIR }) {
  await mkdir(target, { recursive: true });
  const written = [];
  for await (const rel of templateFiles(templateDir)) {
    const parts = rel.split(path.sep);
    parts[parts.length - 1] = RENAMES[parts.at(-1)] ?? parts.at(-1);
    const destRel = parts.join(path.sep);
    if (path.basename(destRel).toLowerCase() === ".env") {
      throw new Error("Refusing to write .env: projects only get .env.example.");
    }
    const text = render(await readFile(path.join(templateDir, rel), "utf8"), values, rel);
    await mkdir(path.dirname(path.join(target, destRel)), { recursive: true });
    await writeFile(path.join(target, destRel), text, { encoding: "utf8", flag: "wx" }); // never overwrite
    written.push(destRel.split(path.sep).join("/"));
  }
  return written.sort();
}
