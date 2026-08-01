#!/usr/bin/env node

/**
 * Memory benchmark for the PostHog dev app.
 *
 * Samples RSS across the app's entire process tree (main, renderers, GPU,
 * utility, workspace-server, spawned agents) plus the renderer JS heap over
 * CDP, and reports a steady-state total suitable for before/after comparison.
 *
 * Usage:
 *   node scripts/bench-memory.mjs [--port 9223] [--duration 30] [--interval 2]
 *                                 [--label idle] [--out results.json]
 *
 * The app must already be running in dev with CDP enabled
 * (POSTHOG_CODE_CDP_PORT=<port> pnpm dev:code). The root process is located
 * via the CDP listener, so no pid needs to be passed.
 *
 * Prints a JSON report and, as the final line, `TOTAL_RSS_MB=<median total>`
 * so callers can extract the metric with `tail -1`.
 */

import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
}

const port = Number(arg("port", process.env.POSTHOG_CODE_CDP_PORT ?? 9223));
const durationS = Number(arg("duration", 30));
const intervalS = Number(arg("interval", 2));
const label = arg("label", "unlabeled");
const outFile = arg("out", null);

function fail(message) {
  console.error(`bench-memory: ${message}`);
  process.exit(1);
}

function rootPidFromCdpPort() {
  try {
    const out = execFileSync(
      "lsof",
      ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"],
      { encoding: "utf8" },
    ).trim();
    const pid = Number(out.split("\n")[0]);
    if (!Number.isInteger(pid)) throw new Error("no pid");
    return pid;
  } catch {
    fail(
      `nothing listening on CDP :${port}. Launch the app first: POSTHOG_CODE_CDP_PORT=${port} pnpm dev:code`,
    );
  }
}

function processTable() {
  const out = execFileSync("ps", ["-eo", "pid=,ppid=,rss=,command="], {
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  const rows = [];
  for (const line of out.split("\n")) {
    const m = line.match(/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/);
    if (m) {
      rows.push({
        pid: Number(m[1]),
        ppid: Number(m[2]),
        rssKb: Number(m[3]),
        command: m[4],
      });
    }
  }
  return rows;
}

function descendants(rootPid, rows) {
  const byParent = new Map();
  for (const row of rows) {
    if (!byParent.has(row.ppid)) byParent.set(row.ppid, []);
    byParent.get(row.ppid).push(row);
  }
  const result = [];
  const queue = [rootPid];
  const seen = new Set(queue);
  while (queue.length) {
    const pid = queue.shift();
    const row = rows.find((r) => r.pid === pid);
    if (row) result.push(row);
    for (const child of byParent.get(pid) ?? []) {
      if (!seen.has(child.pid)) {
        seen.add(child.pid);
        queue.push(child.pid);
      }
    }
  }
  return result;
}

function classify(row, rootPid) {
  const c = row.command;
  if (row.pid === rootPid) return "main";
  const type = c.match(/--type=([a-z-]+)/)?.[1];
  if (type === "renderer") return "renderer";
  if (type === "gpu-process") return "gpu";
  if (type === "utility") {
    const sub = c.match(/--utility-sub-type=([a-zA-Z.]+)/)?.[1];
    return sub === "node.mojom.NodeService" ? "utility-node" : "utility";
  }
  if (type) return type;
  if (c.includes("workspace-server")) return "workspace-server";
  if (c.includes("crashpad")) return "crashpad";
  if (/\bnode\b|\.mjs|\.js/.test(c)) return "node-child";
  return "other";
}

async function rendererHeapMb() {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/json/list`, {
      signal: AbortSignal.timeout(2000),
    });
    const targets = await res.json();
    const page = targets.find(
      (t) => t.type === "page" && t.webSocketDebuggerUrl,
    );
    if (!page) return null;
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    const heap = await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 3000);
      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            id: 1,
            method: "Runtime.evaluate",
            params: {
              expression: "performance.memory.usedJSHeapSize",
              returnByValue: true,
            },
          }),
        );
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id === 1) {
          clearTimeout(timer);
          resolve(msg.result?.result?.value ?? null);
        }
      };
      ws.onerror = () => {
        clearTimeout(timer);
        resolve(null);
      };
    });
    ws.close();
    return heap == null ? null : heap / (1024 * 1024);
  } catch {
    return null;
  }
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

const rootPid = rootPidFromCdpPort();
const samples = [];
const sampleCount = Math.max(1, Math.floor(durationS / intervalS));

for (let i = 0; i < sampleCount; i++) {
  const rows = descendants(rootPid, processTable());
  const byCategory = {};
  let totalKb = 0;
  for (const row of rows) {
    const category = classify(row, rootPid);
    byCategory[category] = (byCategory[category] ?? 0) + row.rssKb;
    totalKb += row.rssKb;
  }
  samples.push({
    totalMb: totalKb / 1024,
    byCategoryMb: Object.fromEntries(
      Object.entries(byCategory).map(([k, v]) => [k, +(v / 1024).toFixed(1)]),
    ),
    processCount: rows.length,
    heapMb: await rendererHeapMb(),
  });
  if (i < sampleCount - 1) {
    await new Promise((r) => setTimeout(r, intervalS * 1000));
  }
}

const totalMedianMb = median(samples.map((s) => s.totalMb));
const heapSamples = samples.map((s) => s.heapMb).filter((h) => h != null);
const categories = {};
for (const s of samples) {
  for (const [k, v] of Object.entries(s.byCategoryMb)) {
    categories[k] ??= [];
    categories[k].push(v);
  }
}

const report = {
  label,
  port,
  rootPid,
  samples: samples.length,
  durationS,
  totalRssMb: +totalMedianMb.toFixed(1),
  peakRssMb: +Math.max(...samples.map((s) => s.totalMb)).toFixed(1),
  rendererHeapMb: heapSamples.length ? +median(heapSamples).toFixed(1) : null,
  byCategoryMb: Object.fromEntries(
    Object.entries(categories).map(([k, v]) => [k, +median(v).toFixed(1)]),
  ),
  processCount: Math.round(median(samples.map((s) => s.processCount))),
};

console.log(JSON.stringify(report, null, 2));
if (outFile) appendFileSync(outFile, `${JSON.stringify(report)}\n`);
console.log(`TOTAL_RSS_MB=${report.totalRssMb}`);
