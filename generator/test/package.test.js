// What `npm pack` would publish: an explicit allow-list, nothing else.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const PACKAGE_DIR = fileURLToPath(new URL("..", import.meta.url));

const EXPECTED = [
  "LICENSE",
  "README.md",
  "bin/rag-kit-dev.js",
  "lib/args.js",
  "lib/cli.js",
  "lib/install.js",
  "lib/process.js",
  "lib/prompt.js",
  "lib/python.js",
  "lib/scaffold.js",
  "lib/validate.js",
  "lib/version.js",
  "package.json",
  "templates/default/README.md",
  "templates/default/_env.example",
  "templates/default/_gitignore",
  "templates/default/data/_gitkeep",
  "templates/default/example.py",
  "templates/default/rag-kit.toml",
  "templates/default/requirements.txt.tmpl",
];

// npm's CLI script, run with this node so no shell or npm.cmd is involved.
function npmCli() {
  const candidates = [
    process.env.npm_execpath,
    path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js"),
    path.join(path.dirname(process.execPath), "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
  ];
  return candidates.find((p) => p && p.endsWith(".js") && existsSync(p));
}

const cli = npmCli();

test("npm pack --dry-run contains exactly the allow-listed files", { skip: !cli && "npm CLI not found" }, () => {
  const result = spawnSync(process.execPath, [cli, "pack", "--dry-run", "--json", "--ignore-scripts"], {
    cwd: PACKAGE_DIR, encoding: "utf8", shell: false,
  });
  assert.equal(result.status, 0, result.stderr);
  const [report] = JSON.parse(result.stdout);
  const files = report.files.map((f) => f.path).sort();
  assert.deepEqual(files, EXPECTED);
  assert.equal(report.name, "rag-kit-dev");
  assert.ok(!files.some((f) => /(^|\/)\.env$|^test\/|\.gitattributes/.test(f)), files.join(", "));
});

test("package.json: bin, Node >= 20, no install scripts, no dependencies", () => {
  const pkg = JSON.parse(readFileSync(path.join(PACKAGE_DIR, "package.json"), "utf8"));
  assert.deepEqual(pkg.bin, { "rag-kit-dev": "bin/rag-kit-dev.js" });
  assert.equal(pkg.engines.node, ">=20");
  for (const hook of ["preinstall", "install", "postinstall", "prepare", "prepack", "postpack"]) {
    assert.ok(!(hook in (pkg.scripts ?? {})), hook);
  }
  assert.equal(pkg.dependencies, undefined);
  assert.equal(pkg.license, "MIT");
});

test("the bin script starts with a node shebang and LF line endings", () => {
  const text = readFileSync(path.join(PACKAGE_DIR, "bin", "rag-kit-dev.js"), "utf8");
  assert.ok(text.startsWith("#!/usr/bin/env node\n"), JSON.stringify(text.slice(0, 25)));
});

test("the packaged LICENSE is the project's", { skip: !existsSync(path.join(PACKAGE_DIR, "..", "LICENSE")) && "no root LICENSE" }, () => {
  const normalize = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");
  assert.equal(normalize(path.join(PACKAGE_DIR, "LICENSE")), normalize(path.join(PACKAGE_DIR, "..", "LICENSE")));
});
