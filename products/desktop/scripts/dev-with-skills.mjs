import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { setTimeout } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import {
  REPOSITORY_DIR,
  skillSourceFingerprint,
  syncCheckoutSkills,
} from "./sync-local-skills.mjs";

const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginDir = join(desktopDir, "plugins/posthog");

function run(command, args, { cwd, signal, env = process.env }) {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const child = spawn(command, args, {
      cwd,
      stdio: "inherit",
      detached: process.platform !== "win32",
      env,
    });
    const stop = () => {
      if (!child.pid) return;
      try {
        if (process.platform === "win32") child.kill("SIGTERM");
        else process.kill(-child.pid, "SIGTERM");
      } catch (error) {
        if (error.code !== "ESRCH") throw error;
      }
    };
    signal.addEventListener("abort", stop, { once: true });
    child.on("error", reject);
    child.on("close", (code) => {
      signal.removeEventListener("abort", stop);
      if (code === 0 || signal.aborted) resolve();
      else reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

async function buildSkills(signal) {
  console.log("[skills] Building skills from this checkout...");
  await run(
    "uv",
    ["run", "python", "products/posthog_ai/scripts/build_skills.py"],
    {
      cwd: REPOSITORY_DIR,
      signal,
      env: { ...process.env, DEBUG: "1" },
    },
  );
  signal.throwIfAborted();
  await syncCheckoutSkills({
    checkoutSkillsDir: join(REPOSITORY_DIR, "products/posthog_ai/dist/skills"),
    localSkillsDir: join(pluginDir, "checkout-skills"),
  });
  await writeFile(join(pluginDir, "checkout-skills.ready"), `${Date.now()}\n`);
  console.log(
    "[skills] Local skills ready. Start a new agent session to use them.",
  );
}

async function watchSkills(signal, fingerprint) {
  while (!signal.aborted) {
    await setTimeout(1000, undefined, { signal });
    try {
      const next = await skillSourceFingerprint();
      if (next === fingerprint) continue;
      fingerprint = next;
      await buildSkills(signal);
    } catch (error) {
      if (signal.aborted) return;
      console.error(
        "[skills] Build failed. The last successful local skills remain active. Fix the error and save a skill to retry.",
        error,
      );
    }
  }
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (!command)
    throw new Error(
      "Usage: node scripts/dev-with-skills.mjs <command> [args...]",
    );
  const source = process.env.POSTHOG_DESKTOP_SKILLS ?? "production";
  if (source !== "local" && source !== "production") {
    throw new Error("POSTHOG_DESKTOP_SKILLS must be local or production");
  }
  const controller = new AbortController();
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => controller.abort());
  }
  let watcher;
  try {
    console.log(
      `[skills] Source: ${source}. Manual local-skills overrides remain enabled in development.`,
    );
    if (source === "local") {
      const fingerprint = await skillSourceFingerprint();
      await buildSkills(controller.signal);
      watcher = watchSkills(controller.signal, fingerprint).catch((error) => {
        if (!controller.signal.aborted) throw error;
      });
    }
    await run(command, args, { cwd: desktopDir, signal: controller.signal });
  } finally {
    controller.abort();
    await watcher;
  }
}

await main().catch((error) => {
  if (error.name === "AbortError") return;
  console.error(
    "[skills] Desktop startup stopped. Fix the error before restarting.",
    error,
  );
  process.exitCode = 1;
});
