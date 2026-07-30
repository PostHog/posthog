#!/usr/bin/env node

/**
 * Preflight + connect for driving the running Electron app with agent-browser.
 *
 * Usage: pnpm app:cdp [port]
 *
 * Verifies agent-browser is installed and the dev app is exposing a Chrome
 * DevTools Protocol endpoint (the dev scripts launch with
 * --remote-debugging-port=9222), then connects so subsequent agent-browser
 * commands target the app. Port resolution: first positional arg, then
 * POSTHOG_CODE_CDP_PORT, then 9222.
 */

import { spawnSync } from "node:child_process";

const CDP_FETCH_TIMEOUT_MS = 2000;

const port = Number(
  process.argv[2] ?? process.env.POSTHOG_CODE_CDP_PORT ?? 9222,
);

function fail(message) {
  console.error(`\n✗ ${message}\n`);
  process.exit(1);
}

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  fail(
    `Invalid port "${process.argv[2] ?? process.env.POSTHOG_CODE_CDP_PORT}". Pass an integer 1-65535 (or set POSTHOG_CODE_CDP_PORT).`,
  );
}

const version = spawnSync("agent-browser", ["--version"], { encoding: "utf8" });
if (version.error) {
  if (version.error.code === "ENOENT") {
    fail(
      "agent-browser is not installed.\n  Install it once with:\n    npm i -g agent-browser && agent-browser install",
    );
  }
  fail(`Failed to run agent-browser: ${version.error.message}`);
}

let targets;
try {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`, {
    signal: AbortSignal.timeout(CDP_FETCH_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  targets = await response.json();
} catch {
  fail(
    `Electron app is not reachable on :${port}.\n  Start it with \`pnpm dev\` (or \`pnpm dev:code\`); it launches with --remote-debugging-port=${port}.`,
  );
}

const pages = targets.filter((t) => t.type === "page");
console.log(`✓ ${version.stdout.trim()}`);
console.log(
  `✓ Electron app reachable on :${port} (${pages.length} page target${pages.length === 1 ? "" : "s"})`,
);
for (const page of pages) {
  console.log(`    - ${page.title || "(untitled)"} ${page.url}`);
}

const connect = spawnSync("agent-browser", ["connect", String(port)], {
  stdio: "inherit",
});
if (connect.status !== 0) {
  process.exit(connect.status ?? 1);
}

console.log(
  `\nConnected. Next: agent-browser snapshot -i\nLoad the workflow with: agent-browser skills get electron`,
);
