#!/usr/bin/env node
// Entry point for `npx rag-kit-dev <project-name>`. The Node version check runs
// before any module that needs Node 20 is loaded.

const major = Number(process.versions.node.split(".")[0]);
if (major < 20) {
  process.stderr.write(`rag-kit-dev needs Node.js 20 or newer (this is ${process.versions.node}).\n`);
  process.exit(1);
}

const { main } = await import("../lib/cli.js");
try {
  process.exitCode = await main(process.argv.slice(2));
} catch (error) {
  process.stderr.write(`rag-kit-dev failed unexpectedly: ${error?.stack ?? error}\n`);
  process.exitCode = 1;
}
