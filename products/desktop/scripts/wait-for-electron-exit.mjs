import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WAIT_TIMEOUT_MS = 15_000;
const POLL_INTERVAL_MS = 200;

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const electronDist = path.join(repoRoot, "node_modules", "electron", "dist");
const pattern = electronDist.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function runningElectronPids() {
  try {
    const out = execFileSync("pgrep", ["-f", pattern], { encoding: "utf8" });
    return out.split("\n").filter(Boolean);
  } catch (error) {
    if (error.status === 1) return [];
    throw error;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

if (process.platform !== "win32") {
  try {
    const initialPids = runningElectronPids();
    if (initialPids.length > 0) {
      console.log(
        `Waiting for previous Electron instance to exit (pids: ${initialPids.join(", ")})`,
      );
      const startedAt = Date.now();
      while (Date.now() - startedAt < WAIT_TIMEOUT_MS) {
        await sleep(POLL_INTERVAL_MS);
        if (runningElectronPids().length === 0) break;
      }
      const remaining = runningElectronPids();
      if (remaining.length > 0) {
        console.warn(
          `Previous Electron instance still running after ${WAIT_TIMEOUT_MS}ms (pids: ${remaining.join(", ")}), starting anyway`,
        );
      } else {
        console.log(
          `Previous Electron instance exited after ${((Date.now() - startedAt) / 1000).toFixed(1)}s`,
        );
      }
    }
  } catch (error) {
    console.warn(
      `Skipping wait for previous Electron instance, pgrep failed: ${error.code ?? error.status ?? error.message}`,
    );
  }
}
