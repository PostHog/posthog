#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(desktopRoot, "../..");
const localQuillRoot = join(repositoryRoot, "packages/quill/packages/quill");
const stateDirectory = join(desktopRoot, ".local-quill");
const statePath = join(stateDirectory, "state.json");
const installedQuillPath = join(desktopRoot, "node_modules/@posthog/quill");
const savedQuillPath = join(stateDirectory, "installed-quill");

function fail(message) {
  console.error(`local-quill: ${message}`);
  process.exit(1);
}

function buildQuill() {
  if (!existsSync(join(localQuillRoot, "package.json"))) {
    fail(`Quill source was not found at ${localQuillRoot}`);
  }

  console.log("Building @posthog/quill from the monorepo source...");
  execFileSync("pnpm", ["--filter", "@posthog/quill...", "build"], {
    cwd: repositoryRoot,
    stdio: "inherit",
  });
}

function readState() {
  return existsSync(statePath)
    ? JSON.parse(readFileSync(statePath, "utf8"))
    : null;
}

function pointsToLocalQuill() {
  return (
    existsSync(installedQuillPath) &&
    lstatSync(installedQuillPath).isSymbolicLink() &&
    resolve(dirname(installedQuillPath), readlinkSync(installedQuillPath)) ===
      localQuillRoot
  );
}

function enable() {
  buildQuill();

  if (readState()) {
    if (!pointsToLocalQuill()) {
      fail(
        "saved state exists, but the installed Quill link changed; run `pnpm quill:local disable` first",
      );
    }
    console.log(
      "Local Quill is already enabled; rebuilt it with the latest source.",
    );
    return;
  }

  if (!existsSync(installedQuillPath)) {
    fail(
      "@posthog/quill is not installed; run `pnpm install` in products/desktop first",
    );
  }
  if (existsSync(savedQuillPath)) {
    fail(`${savedQuillPath} already exists; recover it before enabling`);
  }

  mkdirSync(stateDirectory, { recursive: true });
  try {
    renameSync(installedQuillPath, savedQuillPath);
    symlinkSync(
      localQuillRoot,
      installedQuillPath,
      process.platform === "win32" ? "junction" : "dir",
    );
    writeFileSync(statePath, `${JSON.stringify({ enabled: true }, null, 2)}\n`);
  } catch (error) {
    if (pointsToLocalQuill()) {
      rmSync(installedQuillPath, { force: true, recursive: true });
    }
    if (existsSync(savedQuillPath) && !existsSync(installedQuillPath)) {
      renameSync(savedQuillPath, installedQuillPath);
    }
    rmSync(statePath, { force: true });
    throw error;
  }

  console.log("Linked desktop to local @posthog/quill.");
  console.log(
    "Run `pnpm quill:local refresh` after Quill changes, then restart the dev server if needed.",
  );
}

function disable() {
  if (!readState()) {
    console.log("Local Quill is already disabled.");
    return;
  }
  if (!existsSync(savedQuillPath)) {
    fail("the saved pnpm-installed Quill directory is missing");
  }
  if (existsSync(installedQuillPath) && !pointsToLocalQuill()) {
    fail(
      "the installed Quill path no longer points to local Quill; refusing to overwrite it",
    );
  }

  rmSync(installedQuillPath, { force: true, recursive: true });
  renameSync(savedQuillPath, installedQuillPath);
  rmSync(statePath, { force: true });
  console.log("Restored the pnpm-installed @posthog/quill directory.");
}

function status() {
  if (!readState()) {
    console.log("Local Quill is disabled.");
    return;
  }

  console.log(
    `Local Quill is enabled${pointsToLocalQuill() ? "" : ", but its installed link is missing or changed"}.`,
  );
}

const command = process.argv[2];
switch (command) {
  case "enable":
    enable();
    break;
  case "refresh":
    if (!readState()) {
      fail("local Quill is disabled; run `pnpm quill:local enable` first");
    }
    buildQuill();
    console.log("Rebuilt local Quill.");
    break;
  case "disable":
    disable();
    break;
  case "status":
    status();
    break;
  default:
    console.log("Usage: pnpm quill:local <enable|refresh|disable|status>");
    process.exitCode = command ? 1 : 0;
}
