// `npx rag-kit-dev <name>`: validate, choose embeddings, find Python, write the
// project, install it. Nothing is written before every check has passed, and
// nothing is ever deleted - a failed install leaves the project for a retry.

import path from "node:path";

import { parseCliArgs, USAGE, UsageError } from "./args.js";
import { installEnv, installPlan, runSteps } from "./install.js";
import { formatCommand, run as realRun } from "./process.js";
import { CancelledError, chooseEmbeddings, disclosure } from "./prompt.js";
import { findPython, PythonNotFoundError } from "./python.js";
import { scaffold, templateValues } from "./scaffold.js";
import { checkTarget, resolveTarget, validateName, ValidationError } from "./validate.js";
import { RAG_KIT_VERSION } from "./version.js";

export async function main(argv, deps = {}) {
  const {
    platform = process.platform,
    cwd = process.cwd(),
    env = process.env,
    stdin = process.stdin,
    stdout = process.stdout,
    stderr = process.stderr,
    interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY),
    run = realRun,
  } = deps;
  const say = (text = "") => stdout.write(`${text}\n`);
  const fail = (text) => stderr.write(`error: ${text}\n`);

  let options;
  try {
    options = parseCliArgs(argv);
  } catch (error) {
    if (!(error instanceof UsageError)) throw error;
    fail(error.message);
    stderr.write(`\n${USAGE}`);
    return 2;
  }
  if (options.help) { stdout.write(USAGE); return 0; }
  if (options.version) { say(RAG_KIT_VERSION); return 0; }

  // 1. Name and folder - before anything else.
  let target;
  try {
    validateName(options.name);
    target = resolveTarget(options.name, cwd);
    await checkTarget(target);
  } catch (error) {
    if (!(error instanceof ValidationError)) throw error;
    fail(error.message);
    return 2;
  }

  // 2. Embeddings, explained before anything is installed.
  let embeddings;
  try {
    embeddings = await chooseEmbeddings(options, { interactive, input: stdin, output: stdout, platform });
  } catch (error) {
    if (error instanceof UsageError) { fail(error.message); return 2; }
    if (error instanceof CancelledError) { fail(error.message); return 130; }
    throw error;
  }
  say(`\nEmbeddings: ${embeddings}\n${disclosure(embeddings, { platform, gpu: options.gpu })}`);
  if (options.gpu && embeddings === "gemini") say("(--gpu has no effect with Gemini embeddings.)");

  // 3. Installer and Python - still before writing, so a missing Python leaves nothing behind.
  let python = null;
  let useUv = false;
  if (options.install) {
    if (options.useUv) {
      useUv = (await run("uv", ["--version"], { timeoutMs: 30000 })).code === 0;
    }
    try {
      python = await findPython({ platform, explicit: options.python, run });
    } catch (error) {
      if (!(error instanceof PythonNotFoundError)) throw error;
      fail(`${error.message}\nNothing was created.`);
      return 1;
    }
    say(`\nPython: ${python.version} (${python.executable})`);
    say(`Installer: ${useUv ? "uv" : "pip"}${options.useUv && !useUv ? " (uv not found)" : ""}`);
  }

  // 4. Project files.
  const values = templateValues({ name: options.name, embeddings, version: RAG_KIT_VERSION });
  let files;
  try {
    files = await scaffold({ target, values });
  } catch (error) {
    fail(`Could not write the project files in ${target}: ${error.message}\n` +
      "Files written before the error were kept; nothing was deleted.");
    return 1;
  }
  say(`\nCreated ${target}\n  ${files.join("\n  ")}`);

  if (!options.install) {
    say("\nSkipped installation (--no-install).");
    printNextSteps(say, { name: options.name, platform, installed: false, embeddings });
    return 0;
  }

  // 5. Install into the project's .venv.
  const steps = installPlan({
    platform, pythonExecutable: python.executable, useUv, embeddings, gpu: options.gpu,
    packageSpec: options.packageSpec, testPypi: options.testPypi, version: RAG_KIT_VERSION,
  });
  const result = await runSteps(steps, { cwd: target, env: installEnv(env), run, log: say });
  if (!result.ok) {
    fail(`"${result.failed.label}" failed${result.error ? ` (${result.error.message})` : ""}.`);
    say(`\nThe project files in ${target} were kept${result.completed.length
      ? `, and these steps finished: ${result.completed.map((s) => s.label).join("; ")}` : ""}.`);
    say(`To finish, fix the problem above and run, from ${target}:`);
    for (const step of result.remaining) say(`  ${formatCommand(step.command, step.args)}`);
    return 1;
  }
  if (options.packageSpec || options.testPypi) {
    say(`\nNote: requirements.txt pins ${values.RAG_KIT_REQUIREMENT} (the published release); ` +
      "this .venv was installed from the testing source you chose.");
  }
  printNextSteps(say, { name: options.name, platform, installed: true, embeddings });
  return 0;
}

function printNextSteps(say, { name, platform, installed, embeddings }) {
  const windows = platform === "win32";
  say("\nNext steps:");
  say(`  cd ${name}`);
  say(windows ? "  Copy-Item .env.example .env        (cmd: copy .env.example .env)"
    : "  cp .env.example .env");
  say("  # open .env and set GOOGLE_API_KEY (needed for answers); never commit .env");
  if (!installed) {
    say(windows ? "  py -3.11 -m venv .venv" : "  python3.11 -m venv .venv");
    if (embeddings === "local" && platform === "linux") {
      say("  .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu");
    }
    say(windows ? "  .venv\\Scripts\\python.exe -m pip install -r requirements.txt"
      : "  .venv/bin/python -m pip install -r requirements.txt");
  }
  say(windows ? "  .venv\\Scripts\\Activate.ps1          (cmd: .venv\\Scripts\\activate.bat)"
    : "  source .venv/bin/activate");
  say("  rag-kit check");
  say("  rag-kit ingest data/your-document.pdf");
  say('  rag-kit ask "your question"');
  say(`\nSee ${path.join(name, "README.md")} for more.`);
}
