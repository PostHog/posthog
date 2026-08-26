import * as fs from "node:fs";
import * as path from "node:path";
import type { CodexSubscriptionStatus } from "./schemas";

// Existence checks only; the user's ~/.codex/auth.json is never opened or copied.
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

export function hasSubscriptionLogin(subscriptionHomeDir: string): boolean {
  return fs.existsSync(path.join(subscriptionHomeDir, "auth.json"));
}

// Removes only the app's own stored login, never the user's ~/.codex.
export async function clearSubscriptionLogin(
  subscriptionHomeDir: string,
): Promise<void> {
  await fs.promises.rm(path.join(subscriptionHomeDir, "auth.json"), {
    force: true,
  });
}
