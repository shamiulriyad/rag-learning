// Command-line arguments for `npx rag-kit-dev <name> [options]`.

import { parseArgs } from "node:util";

export const EMBEDDING_CHOICES = ["local", "gemini"];

export const USAGE = `Usage: npx rag-kit-dev <project-name> [options]

Creates a new folder <project-name> with a rag-kit project and, unless
--no-install is given, a .venv with rag-kit installed.

Options:
  --embeddings local|gemini  how the project creates embeddings (asked if omitted;
                             required when not running in an interactive terminal)
  --gpu                      local embeddings on Linux: keep PyTorch's CUDA build
                             (default: CPU-only PyTorch)
  --python PATH              Python 3.11 or 3.12 interpreter to use
  --no-uv                    use pip even if uv is installed
  --no-install               only write the project files
  -y, --yes                  never prompt (needs --embeddings)
  -h, --help                 show this help
  -v, --version              show the generator version

Testing only (before rag-kit is published, or for release candidates):
  --package-spec SPEC        install rag-kit from SPEC instead of PyPI, e.g. a
                             local wheel path or "rag-kit==0.1.0rc1"
  --test-pypi                install from TestPyPI (dependencies from PyPI)
`;

export class UsageError extends Error {}

const OPTIONS = {
  embeddings: { type: "string" },
  gpu: { type: "boolean" },
  python: { type: "string" },
  "no-uv": { type: "boolean" },
  "no-install": { type: "boolean" },
  yes: { type: "boolean", short: "y" },
  "package-spec": { type: "string" },
  "test-pypi": { type: "boolean" },
  help: { type: "boolean", short: "h" },
  version: { type: "boolean", short: "v" },
};

export function parseCliArgs(argv) {
  let parsed;
  try {
    parsed = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true, strict: true });
  } catch (error) {
    throw new UsageError(error.message);
  }
  const { values, positionals } = parsed;
  const options = {
    help: Boolean(values.help),
    version: Boolean(values.version),
    name: positionals[0],
    embeddings: values.embeddings,
    gpu: Boolean(values.gpu),
    python: values.python,
    useUv: !values["no-uv"],
    install: !values["no-install"],
    yes: Boolean(values.yes),
    packageSpec: values["package-spec"],
    testPypi: Boolean(values["test-pypi"]),
  };
  if (options.help || options.version) {
    return options;
  }
  if (positionals.length === 0) {
    throw new UsageError("Missing the project name, e.g. `npx rag-kit-dev my-rag`.");
  }
  if (positionals.length > 1) {
    throw new UsageError(`Expected one project name, got ${positionals.length}: ${positionals.join(" ")}`);
  }
  if (options.embeddings !== undefined && !EMBEDDING_CHOICES.includes(options.embeddings)) {
    throw new UsageError(`--embeddings must be "local" or "gemini", got "${options.embeddings}".`);
  }
  for (const key of ["python", "packageSpec"]) {
    if (options[key] !== undefined && options[key].trim() === "") {
      throw new UsageError(`--${key === "python" ? "python" : "package-spec"} needs a value.`);
    }
  }
  return options;
}
