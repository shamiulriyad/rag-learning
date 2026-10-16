// Finds a Python 3.11 or 3.12 interpreter. 3.11 is preferred (the version
// rag-kit is tested on most), then 3.12.

export const SUPPORTED = ["3.11", "3.12"];

export class PythonNotFoundError extends Error {}

const PROBE =
  "import json, sys; print(json.dumps({'version': '%d.%d.%d' % sys.version_info[:3], " +
  "'executable': sys.executable}))";

export function candidates(platform, explicit) {
  if (explicit) {
    return [{ command: explicit, args: [] }];
  }
  if (platform === "win32") {
    return [
      { command: "py", args: ["-3.11"] },
      { command: "py", args: ["-3.12"] },
      { command: "python", args: [] },
      { command: "python3", args: [] },
    ];
  }
  return [
    { command: "python3.11", args: [] },
    { command: "python3.12", args: [] },
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ];
}

// run(command, args, options) -> { code, stdout } (see process.js); injected for tests.
export async function findPython({ platform, explicit, run }) {
  const tried = [];
  for (const candidate of candidates(platform, explicit)) {
    const label = [candidate.command, ...candidate.args].join(" ");
    const result = await run(candidate.command, [...candidate.args, "-c", PROBE], { timeoutMs: 30000 });
    let info = null;
    if (result.code === 0) {
      try {
        info = JSON.parse(result.stdout.trim().split(/\r?\n/).pop());
      } catch {
        info = null;
      }
    }
    if (!info?.version || !info?.executable) {
      tried.push(`${label}: not available`);
      continue;
    }
    const minor = info.version.split(".").slice(0, 2).join(".");
    if (SUPPORTED.includes(minor)) {
      return { executable: info.executable, version: info.version, label };
    }
    tried.push(`${label}: Python ${info.version} (rag-kit needs 3.11 or 3.12)`);
  }
  const how = explicit
    ? `--python ${explicit} is not a Python 3.11 or 3.12 interpreter.`
    : "No Python 3.11 or 3.12 interpreter was found.";
  throw new PythonNotFoundError(
    `${how}\n  Tried:\n    ${tried.join("\n    ")}\n` +
      "  Install Python 3.11 (https://www.python.org/downloads/) or pass --python PATH, " +
      "or re-run with --no-install to only create the project files.",
  );
}
