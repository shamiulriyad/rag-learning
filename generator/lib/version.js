// The generator's own version, which is also the rag-kit version it installs.

import { readFileSync } from "node:fs";

export const RAG_KIT_VERSION = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
).version;
