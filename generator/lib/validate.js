// Project name and target folder checks. Everything here runs before any file is written.

import { readdir, stat } from "node:fs/promises";
import path from "node:path";

export class ValidationError extends Error {}

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,213}$/;
// Device names Windows reserves in every folder, with or without an extension.
const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$/i;

export function validateName(name) {
  if (name === "." || name === "..") {
    throw new ValidationError(
      `"${name}" is not supported: rag-kit-dev creates a new folder. Pass a name such as my-rag.`,
    );
  }
  if (/[\\/:]/.test(name)) {
    throw new ValidationError(
      `"${name}" looks like a path. Pass only a folder name; it is created in the current directory.`,
    );
  }
  if (!NAME_PATTERN.test(name)) {
    throw new ValidationError(
      `"${name}" is not a valid project name. Use letters, digits, ".", "_" and "-", ` +
        "starting with a letter or digit (at most 214 characters).",
    );
  }
  if (name.endsWith(".")) {
    throw new ValidationError(`"${name}" ends with "." which Windows cannot use as a folder name.`);
  }
  if (WINDOWS_RESERVED.test(name)) {
    throw new ValidationError(`"${name}" is a reserved device name on Windows. Choose another name.`);
  }
  return name;
}

// The folder to create: directly inside `cwd`, never anywhere else.
export function resolveTarget(name, cwd) {
  const base = path.resolve(cwd);
  const target = path.resolve(base, name);
  if (path.dirname(target) !== base) {
    throw new ValidationError(`"${name}" would not be created inside ${base}.`);
  }
  return target;
}

// A missing folder or an empty one is fine; anything else is refused.
export async function checkTarget(target) {
  let info;
  try {
    info = await stat(target);
  } catch (error) {
    if (error.code === "ENOENT") {
      return { exists: false };
    }
    throw error;
  }
  if (!info.isDirectory()) {
    throw new ValidationError(`${target} already exists and is not a folder.`);
  }
  const entries = await readdir(target);
  if (entries.length > 0) {
    throw new ValidationError(
      `${target} already exists and is not empty (${entries.length} entries). ` +
        "Choose another name or an empty folder; nothing was changed.",
    );
  }
  return { exists: true };
}
