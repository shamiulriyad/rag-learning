// Builds the install steps as plain data, so every platform's commands can be
// tested anywhere; runSteps() executes them.

import path from "node:path";

import { formatCommand } from "./process.js";

export const CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu";
export const TEST_PYPI_INDEX = "https://test.pypi.org/simple/";

export function extrasFor(embeddings) {
  return embeddings === "local" ? ["local", "gemini"] : ["gemini"];
}

// The dependency written to requirements.txt: always the published release.
export function pinnedRequirement(embeddings, version) {
  return `ragkit-dev[${extrasFor(embeddings).join(",")}]==${version}`;
}

// A requirement (not a file name such as rag_kit-0.1.0-py3-none-any.whl) that names
// the old distribution name rag-kit, which is never published.
const LEGACY_REQUIREMENT = /^\s*rag[-_.]+kit\s*(\[[^\]]*\])?\s*($|[=<>!~;@])/i;

// The message for a --package-spec that names rag-kit, or null.
export function legacyPackageSpecError(spec) {
  if (!LEGACY_REQUIREMENT.test(spec)) {
    return null;
  }
  const suggestion = spec.trim().replace(/^rag[-_.]+kit/i, "ragkit-dev");
  return `--package-spec "${spec.trim()}": the Python distribution is ragkit-dev, not rag-kit; ` +
    `use "${suggestion}".`;
}

// The install runs inside the new project folder, so a local path given to
// --package-spec (as pip tells paths from requirements: a path separator, a
// leading ".", or an archive name) is made absolute from the folder the command
// was run in. Requirements and URLs are returned unchanged.
export function resolvePackageSpec(spec, cwd, platform = process.platform) {
  const text = spec.trim();
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text) || text.includes("@")) {
    return spec;
  }
  if (/[\\/]/.test(text) || text.startsWith(".") || /\.(whl|tar\.gz|zip)$/i.test(text)) {
    return (platform === "win32" ? path.win32 : path.posix).resolve(cwd, text);
  }
  return spec;
}

// What to install for --package-spec: a requirement string gets the extras
// added after its name; anything else (a wheel, an sdist, a folder) gets them appended.
export function packageSpecWithExtras(spec, embeddings) {
  const legacy = legacyPackageSpecError(spec);
  if (legacy) {
    throw new Error(legacy);
  }
  const extras = `[${extrasFor(embeddings).join(",")}]`;
  const named = spec.match(/^\s*ragkit[-_.]+dev\s*(\[[^\]]*\])?\s*(.*)$/i);
  if (named) {
    return `ragkit-dev${extras}${named[2] ? named[2].trim() : ""}`;
  }
  return `${spec}${extras}`;
}

export function venvPython(platform) {
  return platform === "win32" ? path.win32.join(".venv", "Scripts", "python.exe") : ".venv/bin/python";
}

// Ordered steps, each { label, command, args }. All run inside the project folder.
export function installPlan({ platform, pythonExecutable, useUv, embeddings, gpu, packageSpec, testPypi, version }) {
  const python = venvPython(platform);
  const pipInstall = useUv
    ? (args) => ({ command: "uv", args: ["pip", "install", "--python", python, ...args] })
    : (args) => ({ command: python, args: ["-m", "pip", "install", "--disable-pip-version-check", ...args] });

  const steps = [];
  steps.push(useUv
    ? { label: "Create .venv (uv)", command: "uv", args: ["venv", ".venv", "--python", pythonExecutable] }
    : { label: "Create .venv", command: pythonExecutable, args: ["-m", "venv", ".venv"] });

  if (embeddings === "local" && platform === "linux" && !gpu) {
    steps.push({ label: "Install CPU-only PyTorch", ...pipInstall(["torch", "--index-url", CPU_TORCH_INDEX]) });
  }

  if (testPypi) {
    // rag-kit itself from TestPyPI without dependencies, then everything else from
    // PyPI: TestPyPI must never supply third-party packages.
    const spec = packageSpec ? packageSpecWithExtras(packageSpec, embeddings).replace(/\[[^\]]*\]/, "")
      : `ragkit-dev==${version}`;
    steps.push({ label: "Install rag-kit from TestPyPI (no dependencies)",
      ...pipInstall(["--no-deps", "--index-url", TEST_PYPI_INDEX, spec]) });
    steps.push({ label: "Install rag-kit's dependencies from PyPI",
      ...pipInstall([packageSpec ? packageSpecWithExtras(packageSpec, embeddings) : pinnedRequirement(embeddings, version)]) });
  } else if (packageSpec) {
    steps.push({ label: "Install rag-kit from --package-spec",
      ...pipInstall([packageSpecWithExtras(packageSpec, embeddings)]) });
  } else {
    steps.push({ label: "Install rag-kit (requirements.txt)", ...pipInstall(["-r", "requirements.txt"]) });
  }
  return steps;
}

// Environment for the install commands: never let uv download its own Python.
export function installEnv(baseEnv) {
  return { ...baseEnv, UV_PYTHON_DOWNLOADS: "never" };
}

// Runs steps in order and stops at the first failure.
// Returns { ok, completed: [step], failed: step|null, remaining: [step] }.
export async function runSteps(steps, { cwd, env, run, log }) {
  const completed = [];
  for (let i = 0; i < steps.length; i += 1) {
    const step = steps[i];
    log(`\n> ${step.label}\n  ${formatCommand(step.command, step.args)}`);
    // A relative program path (.venv/bin/python) is the project's: resolve it here
    // instead of relying on how each OS resolves relative executables.
    const command = /[\\/]/.test(step.command) && !path.isAbsolute(step.command)
      ? path.resolve(cwd, step.command) : step.command;
    const result = await run(command, step.args, { cwd, env, inherit: true });
    if (result.code !== 0) {
      return { ok: false, completed, failed: step, remaining: steps.slice(i), error: result.error };
    }
    completed.push(step);
  }
  return { ok: true, completed, failed: null, remaining: [] };
}
