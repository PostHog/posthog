#!/usr/bin/env node

/**
 * Launch a second dev instance of the app under a named profile, so you can be
 * signed in as two different users at once and exercise multiplayer features.
 *
 * Usage: pnpm dev:profile <name>          (e.g. pnpm dev:profile alice)
 *
 * `pnpm dev` must already be running: this reuses its renderer dev server and
 * its compiled main bundle rather than starting a second Vite. Main-process
 * edits therefore do NOT hot-reload here — quit and re-run after one.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEV_SERVER_FETCH_TIMEOUT_MS = 2000;
const DEFAULT_RENDERER_URL = "http://localhost:5173";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const appDir = path.join(repoRoot, "apps", "code");
const mainBundle = path.join(appDir, ".vite", "build", "bootstrap.js");

function fail(message) {
  console.error(`\n✗ ${message}\n`);
  process.exit(1);
}

const profile = process.argv[2];
if (!profile || profile.startsWith("-")) {
  fail("Pass a profile name, e.g. `pnpm dev:profile alice`.");
}

const rendererUrl = process.env.ELECTRON_RENDERER_URL ?? DEFAULT_RENDERER_URL;

try {
  const response = await fetch(rendererUrl, {
    signal: AbortSignal.timeout(DEV_SERVER_FETCH_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
} catch {
  fail(
    `Renderer dev server is not reachable at ${rendererUrl}.\n  Start the app with \`pnpm dev\` first, then re-run this.`,
  );
}

if (!existsSync(mainBundle)) {
  fail(
    `No compiled main bundle at ${mainBundle}.\n  Start the app with \`pnpm dev\` first, then re-run this.`,
  );
}

const require = createRequire(path.join(appDir, "package.json"));
const electronPath = require("electron");

console.log(`Starting profile "${profile}" against ${rendererUrl}`);

const child = spawn(
  electronPath,
  [appDir, `--posthog-profile=${profile}`, ...process.argv.slice(3)],
  {
    cwd: appDir,
    stdio: "inherit",
    env: { ...process.env, ELECTRON_RENDERER_URL: rendererUrl },
  },
);

child.on("exit", (code, signal) => {
  process.exit(signal ? 1 : (code ?? 0));
});
