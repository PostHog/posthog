import { spawn } from "node:child_process";

const ELECTRON_WAIT_SCRIPT = "scripts/wait-for-electron-exit.mjs";
const RESTART_DELAY_MS = 1_000;
const RAPID_RESTART_WINDOW_MS = 30_000;
const MAX_RAPID_RESTARTS = 5;
const HEALTH_CHECK_TIMEOUT_MS = 60_000;
const HEALTH_CHECK_INTERVAL_MS = 500;

let child = null;
let stopping = false;
let launchId = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function log(message) {
  process.stdout.write(`[dev-electron] ${message}\n`);
}

function warn(message) {
  process.stderr.write(`[dev-electron] ${message}\n`);
}

function spawnProcess(command, args) {
  return spawn(command, args, {
    stdio: "inherit",
    env: process.env,
  });
}

function runProcess(command, args) {
  return new Promise((resolve) => {
    const proc = spawnProcess(command, args);
    proc.on("close", (code, signal) => resolve({ code, signal }));
  });
}

async function waitForPreviousElectron() {
  const result = await runProcess(process.execPath, [ELECTRON_WAIT_SCRIPT]);
  if (result.code && result.code !== 0) {
    warn(
      `${ELECTRON_WAIT_SCRIPT} exited with ${result.code}; continuing with launch`,
    );
  }
}

async function waitForCdpReady(currentLaunchId) {
  const port = process.env.POSTHOG_CODE_CDP_PORT ?? "9222";
  const deadline = Date.now() + HEALTH_CHECK_TIMEOUT_MS;

  while (
    !stopping &&
    currentLaunchId === launchId &&
    Date.now() < deadline
  ) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) {
        log(`Electron is reachable on CDP :${port}`);
        return;
      }
    } catch {}
    await sleep(HEALTH_CHECK_INTERVAL_MS);
  }

  if (!stopping && currentLaunchId === launchId) {
    warn(`Electron was not reachable on CDP :${port} after 60s`);
  }
}

function requestStop(signal) {
  if (stopping) return;
  stopping = true;
  log(`Received ${signal}, stopping Electron dev process`);
  if (child && !child.killed) {
    child.kill(signal);
  } else {
    process.exit(0);
  }
}

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(signal, () => requestStop(signal));
}

const restartTimestamps = [];

function recordRestartAttempt() {
  const now = Date.now();
  while (
    restartTimestamps.length > 0 &&
    now - restartTimestamps[0] > RAPID_RESTART_WINDOW_MS
  ) {
    restartTimestamps.shift();
  }
  restartTimestamps.push(now);
  return restartTimestamps.length;
}

while (!stopping) {
  await waitForPreviousElectron();
  if (stopping) break;

  const currentLaunchId = ++launchId;
  log("Starting electron-vite dev --watch");
  child = spawnProcess("pnpm", ["--filter", "code", "run", "start"]);
  void waitForCdpReady(currentLaunchId);

  const { code, signal } = await new Promise((resolve) => {
    child.on("close", (exitCode, exitSignal) =>
      resolve({ code: exitCode, signal: exitSignal }),
    );
  });
  child = null;

  if (stopping) {
    process.exit(code ?? 0);
  }

  const attempts = recordRestartAttempt();
  const reason =
    signal ? `signal ${signal}` : `exit code ${code ?? "unknown"}`;

  if (attempts >= MAX_RAPID_RESTARTS) {
    warn(
      `Electron dev exited ${attempts} times in ${RAPID_RESTART_WINDOW_MS / 1000}s (${reason}); not restarting`,
    );
    process.exit(code ?? 1);
  }

  log(`Electron dev exited with ${reason}; restarting in 1s`);
  await sleep(RESTART_DELAY_MS);
}
