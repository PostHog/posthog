import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearSubscriptionLogin,
  detectCodexSubscriptionStatus,
} from "./codex-subscription";

let root: string;
let homeDir: string;
let subscriptionHomeDir: string;

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "codex-subscription-test-"));
  homeDir = path.join(root, "home");
  subscriptionHomeDir = path.join(root, "codex-home-subscription");
  await mkdir(homeDir, { recursive: true });
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("codex subscription detection", () => {
  it("reports each signal from its own location", async () => {
    const bare = detectCodexSubscriptionStatus({
      env: {},
      homeDir,
      subscriptionHomeDir,
      findOnPath: () => undefined,
    });
    expect(bare).toEqual({
      cliInstalled: false,
      credentialFilePresent: false,
      appLoggedIn: false,
    });

    await mkdir(path.join(homeDir, ".codex"), { recursive: true });
    await writeFile(path.join(homeDir, ".codex", "auth.json"), "{}");
    await mkdir(subscriptionHomeDir, { recursive: true });
    await writeFile(path.join(subscriptionHomeDir, "auth.json"), "{}");

    const detected = detectCodexSubscriptionStatus({
      env: {},
      homeDir,
      subscriptionHomeDir,
      findOnPath: (bin) =>
        bin === "codex" ? "/usr/local/bin/codex" : undefined,
    });
    expect(detected).toEqual({
      cliInstalled: true,
      credentialFilePresent: true,
      appLoggedIn: true,
    });
  });

  it("clearSubscriptionLogin removes only the app's own login file", async () => {
    await mkdir(path.join(homeDir, ".codex"), { recursive: true });
    await writeFile(path.join(homeDir, ".codex", "auth.json"), "{}");
    await mkdir(subscriptionHomeDir, { recursive: true });
    await writeFile(path.join(subscriptionHomeDir, "auth.json"), "{}");
    await writeFile(path.join(subscriptionHomeDir, "config.toml"), "");

    await clearSubscriptionLogin(subscriptionHomeDir);

    expect(existsSync(path.join(subscriptionHomeDir, "auth.json"))).toBe(false);
    expect(existsSync(path.join(subscriptionHomeDir, "config.toml"))).toBe(
      true,
    );
    expect(existsSync(path.join(homeDir, ".codex", "auth.json"))).toBe(true);
  });
});
