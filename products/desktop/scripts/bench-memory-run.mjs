#!/usr/bin/env node

/**
 * End-to-end memory benchmark run for the PostHog dev app.
 *
 * Owns the full lifecycle so every run is comparable:
 *   1. launches a fresh dev app (POSTHOG_CODE_CDP_PORT, default :9223)
 *   2. waits for CDP + boot settle
 *   3. samples idle RSS (scripts/bench-memory.mjs)
 *   4. drives the reported-hot user workflow over CDP with playwright-core:
 *      sends N cheap agent turns in the restored thread and waits for replies
 *   5. samples post-workflow RSS
 *   6. tears the app down
 *
 * Usage:
 *   node scripts/bench-memory-run.mjs [--port 9223] [--messages 2]
 *     [--label <label>] [--out results.jsonl] [--idle-only]
 *     [--scenario thread|switch|longout]
 *     [--thread-task-id <id>] [--thread-title <title>]
 *
 * Prints a JSON report; final line is `TOTAL_RSS_MB=<post-workflow median>`
 * (idle median with --idle-only) for predicate extraction via `tail -1`.
 *
 * NOTE: workflow turns hit the real agent backend with trivial prompts
 * ("reply with exactly <token>") to keep token cost minimal while exercising
 * the real agent-session memory path.
 *
 * IMPORTANT: the `thread` and `longout` scenarios send turns into a dedicated
 * throwaway task so benchmark chatter never lands in real work. The default
 * --thread-task-id/--thread-title point at the original author's local bench
 * task — in any other environment, create a scratch task once and pass its id
 * and title explicitly, or the run aborts with "refusing to send benchmark
 * turns".
 */

import { execFileSync, spawn } from "node:child_process";
import { appendFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
}
const flag = (name) => args.includes(`--${name}`);

const port = Number(arg("port", 9223));
const messageCount = Number(arg("messages", 2));
const label = arg("label", "run");
const outFile = arg("out", null);
const idleOnly = flag("idle-only");
/**
 * thread  — N cheap agent turns in the restored thread (default)
 * switch  — visit up to N tasks in the sidebar, then return to the first
 * longout — one turn with a large (~40KB) bash tool output
 */
const scenario = arg("scenario", "thread");

const BOOT_SETTLE_MS = 20_000;
const CDP_TIMEOUT_MS = 120_000;
const REPLY_TIMEOUT_MS = 120_000;
const POST_WORKFLOW_SETTLE_MS = 10_000;

function log(message) {
  console.error(`[bench-run] ${message}`);
}

async function portListening() {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/json/version`, {
      signal: AbortSignal.timeout(1500),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function sample(sampleLabel, durationS) {
  const out = execFileSync(
    process.execPath,
    [
      path.join(repoRoot, "scripts/bench-memory.mjs"),
      "--port",
      String(port),
      "--duration",
      String(durationS),
      "--interval",
      "2",
      "--label",
      sampleLabel,
    ],
    { encoding: "utf8" },
  );
  const json = out.slice(0, out.lastIndexOf("TOTAL_RSS_MB="));
  return JSON.parse(json);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function withRendererPage(fn) {
  const { chromium } = await import(
    path.join(repoRoot, "node_modules/playwright-core/index.mjs")
  );
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  try {
    const pages = browser.contexts().flatMap((c) => c.pages());
    const page = pages.find((p) => !p.url().startsWith("devtools://"));
    if (!page) throw new Error("no renderer page target found");
    return await fn(page);
  } finally {
    // Do not close the app's window; disconnecting the CDP session is enough.
    await browser.close().catch(() => {});
  }
}

async function sendTurn(page, prompt, doneMarker) {
  const composer = page.locator('[contenteditable="true"]').last();
  await composer.waitFor({ state: "visible", timeout: 30_000 });
  const started = Date.now();
  await composer.click();
  await composer.pressSequentially(prompt);
  await page.getByRole("button", { name: "Send message" }).click();
  // The reply contains the marker; the composed message shows it too, so
  // wait for at least two occurrences in the page text.
  await page.waitForFunction(
    (t) => document.body.innerText.split(t).length - 1 >= 2,
    doneMarker,
    { timeout: REPLY_TIMEOUT_MS, polling: 1000 },
  );
  return Date.now() - started;
}

/**
 * Navigate to the dedicated local bench task before sending anything — the
 * restored-at-boot task can be a real work task, and benchmark turns must
 * never land in one.
 */
async function openBenchTask(page) {
  const taskId = arg("thread-task-id", "5feefee1-c818-4931-84c7-e4a68d37b4f0");
  const title = arg("thread-title", "Casual greeting");
  await page.evaluate((id) => {
    window.location.hash = `#/code/tasks/${id}`;
  }, taskId);
  await page.waitForTimeout(6000);
  const header = await page
    .locator("span.rt-truncate")
    .first()
    .textContent()
    .catch(() => "");
  if (!header?.includes(title)) {
    throw new Error(
      `refusing to send benchmark turns: open task is "${header}", expected "${title}". ` +
        `Create a throwaway task in your environment and pass --thread-task-id/--thread-title.`,
    );
  }
}

/** N cheap agent turns in the dedicated bench thread. */
async function driveThread(page) {
  await openBenchTask(page);
  const turns = [];
  for (let i = 0; i < messageCount; i++) {
    const token = `pong-${label}-${i}`;
    const ms = await sendTurn(
      page,
      `Reply with exactly: ${token} (benchmark turn, nothing else)`,
      token,
    );
    turns.push({ token, ms });
    log(`turn ${i + 1}/${messageCount} done in ${ms}ms`);
  }
  return { turns };
}

/**
 * One turn whose tool output is large (~40KB streamed to the transcript),
 * exercising event streaming + conversation rendering, then a settle.
 */
async function driveLongOutput(page) {
  await openBenchTask(page);
  const token = `longout-${label}`;
  const ms = await sendTurn(
    page,
    `Run this exact bash command: seq 1 5000 — then reply with exactly: ${token}`,
    token,
  );
  log(`long-output turn done in ${ms}ms`);
  return { turns: [{ token, ms }] };
}

/**
 * Hop across up to `messageCount` tasks in the sidebar (the realest daily
 * workflow): expand the repo group, visit each task with a dwell so its
 * transcript loads and its session connects, then return to the first.
 */
async function driveSwitch(page) {
  const group = page.getByRole("button", { name: "posthog", exact: true });
  if ((await group.getAttribute("aria-expanded")) === "false") {
    await group.click();
    await page.waitForTimeout(1500);
  }
  // Task rows are the only buttons with long accessible names.
  const names = (
    await page
      .getByRole("button")
      .evaluateAll((els) =>
        els.map(
          (el) => el.getAttribute("aria-label") || el.textContent?.trim() || "",
        ),
      )
  )
    // Row names end with a live relative-time suffix ("… 5m") that goes stale
    // between enumeration and click; match on a title prefix instead.
    .map((n) => n.replace(/\s*\d+[smhd]$/, "").slice(0, 40))
    .filter((n) => n.length >= 30);
  const visits = [];
  const targets = names.slice(0, Math.max(2, messageCount));
  for (const name of targets) {
    const started = Date.now();
    await page.getByRole("button", { name }).first().click();
    await page.waitForTimeout(8000);
    visits.push({ task: name, ms: Date.now() - started });
    log(`visited: ${name}`);
  }
  // Best-effort return to the first task; the list may have re-sorted or
  // virtualized it away, and the post-visit state is the measurement anyway.
  if (targets.length) {
    try {
      await page
        .getByRole("button", { name: targets[0] })
        .first()
        .click({ timeout: 5000 });
      await page.waitForTimeout(5000);
    } catch {
      log("return-to-first skipped (row no longer locatable)");
    }
  }
  return { visits };
}

async function driveWorkflow() {
  return withRendererPage(async (page) => {
    if (scenario === "switch") return driveSwitch(page);
    if (scenario === "longout") return driveLongOutput(page);
    return driveThread(page);
  });
}

if (await portListening()) {
  console.error(
    `bench-run: something already listens on :${port}. This harness owns the app lifecycle; stop the running instance first.`,
  );
  process.exit(1);
}

log("launching dev app...");
const child = spawn("pnpm", ["dev:code"], {
  cwd: repoRoot,
  env: { ...process.env, POSTHOG_CODE_CDP_PORT: String(port) },
  stdio: ["ignore", "ignore", "ignore"],
  detached: true,
});

function teardown() {
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {}
}
process.on("exit", teardown);
process.on("SIGINT", () => process.exit(130));
process.on("SIGTERM", () => process.exit(143));

const deadline = Date.now() + CDP_TIMEOUT_MS;
while (!(await portListening())) {
  if (Date.now() > deadline) {
    console.error("bench-run: app never opened CDP port");
    process.exit(1);
  }
  await sleep(1000);
}
log(`CDP up on :${port}, settling ${BOOT_SETTLE_MS / 1000}s...`);
await sleep(BOOT_SETTLE_MS);

const idle = sample(`${label}-idle`, 20);
log(`idle: ${idle.totalRssMb}MB`);

let workflow = null;
let post = null;
if (!idleOnly) {
  workflow = await driveWorkflow();
  workflow.scenario = scenario;
  await sleep(POST_WORKFLOW_SETTLE_MS);
  post = sample(`${label}-post`, 30);
  log(`post-workflow: ${post.totalRssMb}MB`);
}

teardown();

const report = {
  label,
  port,
  messages: idleOnly ? 0 : messageCount,
  idle,
  workflow,
  post,
  metricMb: idleOnly ? idle.totalRssMb : post.totalRssMb,
};
console.log(JSON.stringify(report, null, 2));
if (outFile) appendFileSync(outFile, `${JSON.stringify(report)}\n`);
console.log(`TOTAL_RSS_MB=${report.metricMb}`);
