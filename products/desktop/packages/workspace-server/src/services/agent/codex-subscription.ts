import * as fs from "node:fs";
import * as path from "node:path";
import type { CodexSubscriptionStatus } from "./schemas";

/**
 * Detects whether this host can run Codex on the user's own ChatGPT
 * subscription. Existence checks only: the user's `~/.codex/auth.json` is
 * never opened, parsed, or copied — the sign-in for PostHog sessions runs
 * through Codex's own login flow into the app's subscription CODEX_HOME.
 */
export function detectCodexSubscriptionStatus(input: {
  env: NodeJS.ProcessEnv;
  homeDir: string;
  subscriptionHomeDir: string;
  findOnPath: (bin: string, env: NodeJS.ProcessEnv) => string | undefined;
}): CodexSubscriptionStatus {
  return {
    cliInstalled: input.findOnPath("codex", input.env) !== undefined,
    credentialFilePresent: fs.existsSync(
      path.join(input.homeDir, ".codex", "auth.json"),
    ),
    appLoggedIn: hasSubscriptionLogin(input.subscriptionHomeDir),
  };
}

/** Whether the app's subscription CODEX_HOME holds a completed ChatGPT login. */
export function hasSubscriptionLogin(subscriptionHomeDir: string): boolean {
  return fs.existsSync(path.join(subscriptionHomeDir, "auth.json"));
}

/** Removes the app's own stored login. Never touches the user's `~/.codex`. */
export async function clearSubscriptionLogin(
  subscriptionHomeDir: string,
): Promise<void> {
  await fs.promises.rm(path.join(subscriptionHomeDir, "auth.json"), {
    force: true,
  });
}
