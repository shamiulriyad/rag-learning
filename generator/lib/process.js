// Runs external programs. Always an argument array and shell: false - nothing
// the user typed is ever interpreted by a shell.

import { spawn } from "node:child_process";

// Resolves (never rejects) with { code, stdout, stderr, error }. code is null
// when the program could not be started or timed out.
export function run(command, args, { cwd, env, timeoutMs, inherit = false } = {}) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, args, {
        cwd,
        env,
        shell: false,
        windowsHide: true,
        stdio: inherit ? "inherit" : ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      resolve({ code: null, stdout: "", stderr: "", error });
      return;
    }
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    const timer = timeoutMs
      ? setTimeout(() => { child.kill(); resolve({ code: null, stdout, stderr, error: new Error("timed out") }); },
        timeoutMs)
      : null;
    child.on("error", (error) => {
      if (timer) clearTimeout(timer);
      resolve({ code: null, stdout, stderr, error });
    });
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      resolve({ code, stdout, stderr, error: null });
    });
  });
}

// How a command line looks to a person who wants to re-run it by hand.
export function formatCommand(command, args) {
  return [command, ...args].map((part) => (/[\s"'&|<>^()]/.test(part) ? `"${part}"` : part)).join(" ");
}
