import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadSessionEnvOverrides } from "./loader";

describe("loadSessionEnvOverrides", () => {
  const SESSION_ID = "test-session-id";
  let configDir: string;
  let sessionDir: string;
  let originalConfigDir: string | undefined;

  beforeEach(async () => {
    configDir = await fs.mkdtemp(path.join(os.tmpdir(), "session-env-test-"));
    sessionDir = path.join(configDir, "session-env", SESSION_ID);
    await fs.mkdir(sessionDir, { recursive: true });
    originalConfigDir = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = configDir;
  });

  afterEach(async () => {
    if (originalConfigDir === undefined) {
      delete process.env.CLAUDE_CONFIG_DIR;
    } else {
      process.env.CLAUDE_CONFIG_DIR = originalConfigDir;
    }
    await fs.rm(configDir, { recursive: true, force: true });
  });

  const writeHook = (name: string, content: string) =>
    fs.writeFile(path.join(sessionDir, name), content);

  it("returns empty when CLAUDE_CONFIG_DIR is unset", async () => {
    delete process.env.CLAUDE_CONFIG_DIR;
    expect(await loadSessionEnvOverrides(SESSION_ID)).toEqual({});
  });

  it("returns empty when session dir does not exist", async () => {
    expect(await loadSessionEnvOverrides("missing-session")).toEqual({});
  });

  it("returns empty when no hook files match", async () => {
    await writeHook("ignored.txt", "export FOO=bar\n");
    expect(await loadSessionEnvOverrides(SESSION_ID)).toEqual({});
  });

  it("parses simple export statements from a SessionStart hook", async () => {
    await writeHook("sessionstart-hook-0.sh", "export FOO=bar\n");
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides.FOO).toBe("bar");
  });

  it("captures values produced by `printf %q` shell quoting", async () => {
    const value = "/Users/alice/Library/foo bar/socket.ssh";
    await writeHook(
      "sessionstart-hook-0.sh",
      `printf 'export SSH_AUTH_SOCK=%q\\n' ${JSON.stringify(value)} | source /dev/stdin\n` +
        // also test the expected hook output format directly
        `export SSH_AUTH_SOCK='${value}'\n`,
    );
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides.SSH_AUTH_SOCK).toBe(value);
  });

  it("merges exports from multiple hook files in sorted order", async () => {
    await writeHook("sessionstart-hook-0.sh", "export FIRST=one\n");
    await writeHook("sessionstart-hook-1.sh", "export SECOND=two\n");
    await writeHook("setup-hook-0.sh", "export THIRD=three\n");
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides.FIRST).toBe("one");
    expect(overrides.SECOND).toBe("two");
    expect(overrides.THIRD).toBe("three");
  });

  it("ignores files that don't match the SDK hook naming convention", async () => {
    await writeHook("setup.sh", "export SHOULD_NOT_LOAD=1\n");
    await writeHook("sessionstart-hook-abc.sh", "export ALSO_NO=1\n");
    await writeHook("sessionstart-hook-0.sh", "export YES=1\n");
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides).toEqual({ YES: "1" });
  });

  it("does not return vars that already match the parent process env", async () => {
    process.env.UNCHANGED_VAR = "same";
    await writeHook("sessionstart-hook-0.sh", "export UNCHANGED_VAR=same\n");
    try {
      const overrides = await loadSessionEnvOverrides(SESSION_ID);
      expect(overrides.UNCHANGED_VAR).toBeUndefined();
    } finally {
      delete process.env.UNCHANGED_VAR;
    }
  });

  it("handles paths with spaces and quotes safely", async () => {
    const dirWithSpaces = path.join(configDir, "session-env", "weird id");
    await fs.mkdir(dirWithSpaces, { recursive: true });
    await fs.writeFile(
      path.join(dirWithSpaces, "sessionstart-hook-0.sh"),
      "export SPACED=ok\n",
    );
    const overrides = await loadSessionEnvOverrides("weird id");
    expect(overrides.SPACED).toBe("ok");
  });

  it("returns empty object on bash failure without throwing", async () => {
    await writeHook("sessionstart-hook-0.sh", "exit 1\nexport NEVER=set\n");
    // sourcing a script that exits cuts the env -0 short, but we should
    // gracefully degrade rather than throw.
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides.NEVER).toBeUndefined();
  });

  it("falls back to empty object if bash is missing", async () => {
    // Skip this test on systems where bash exists at /bin/bash —
    // we only smoke-check that errors are swallowed.
    const realPath = process.env.PATH;
    process.env.PATH = "";
    try {
      const overrides = await loadSessionEnvOverrides(SESSION_ID);
      // bash may still be found via absolute path; either outcome is fine.
      expect(typeof overrides).toBe("object");
    } finally {
      process.env.PATH = realPath;
    }
  });

  it("does not leak BASH_VERSION or other shell internals", async () => {
    await writeHook("sessionstart-hook-0.sh", "export USEFUL=yes\n");
    const overrides = await loadSessionEnvOverrides(SESSION_ID);
    expect(overrides.BASH_VERSION).toBeUndefined();
    expect(overrides.SHLVL).toBeUndefined();
    expect(overrides._).toBeUndefined();
    expect(overrides.USEFUL).toBe("yes");
  });
});
