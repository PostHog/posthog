import { existsSync, readFileSync, realpathSync } from "node:fs";
import { mkdir, mkdtemp, readlink, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const testHome = vi.hoisted(() => ({ dir: "" }));

vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  const homedir = () => testHome.dir;
  return { ...actual, homedir, default: { ...actual, homedir } };
});

import {
  cleanupCodexHome,
  getCodexHomeDir,
  prepareCodexHome,
} from "./codex-home";

const noopLog = { debug() {}, info() {}, warn() {}, error() {} };

const taskRunId = "run-1";

let root: string;
let appDataPath: string;
let bundledSkillsDir: string;
let userSkillsDir: string;

async function createSkill(dir: string, name: string, body = `# ${name}`) {
  await mkdir(path.join(dir, name), { recursive: true });
  await writeFile(path.join(dir, name, "SKILL.md"), body);
}

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "codex-home-test-"));
  testHome.dir = path.join(root, "home");
  appDataPath = path.join(root, "appdata");
  bundledSkillsDir = path.join(root, "bundled", "skills");
  userSkillsDir = path.join(testHome.dir, ".claude", "skills");
  await mkdir(appDataPath, { recursive: true });
  await mkdir(bundledSkillsDir, { recursive: true });
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("prepareCodexHome", () => {
  it("links bundled and user Claude skills into <appData>/codex-home/skills", async () => {
    await createSkill(bundledSkillsDir, "query-data");
    await createSkill(userSkillsDir, "my-skill");

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    expect(codexHome).toBe(path.join(appDataPath, "codex-home", taskRunId));
    const skillsDir = path.join(codexHome, "skills");
    expect(existsSync(path.join(skillsDir, "query-data", "SKILL.md"))).toBe(
      true,
    );
    expect(existsSync(path.join(skillsDir, "my-skill", "SKILL.md"))).toBe(true);
  });

  it("lets the bundled catalog win on a name collision", async () => {
    await createSkill(bundledSkillsDir, "dup", "bundled body");
    await createSkill(userSkillsDir, "dup", "user body");

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const linked = await readlink(path.join(codexHome, "skills", "dup"));
    expect(readFileSync(path.join(linked, "SKILL.md"), "utf-8")).toBe(
      "bundled body",
    );
  });

  it("symlinks the user's ~/.codex/config.toml when present", async () => {
    const codexConfigDir = path.join(testHome.dir, ".codex");
    await mkdir(codexConfigDir, { recursive: true });
    const configPath = path.join(codexConfigDir, "config.toml");
    await writeFile(configPath, 'model = "gpt-5-codex"\n');

    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const link = path.join(codexHome, "config.toml");
    expect(existsSync(link)).toBe(true);
    expect(await readlink(link)).toBe(realpathSync(configPath));
  });

  it("rebuilds the skills dir, dropping stale links", async () => {
    await createSkill(bundledSkillsDir, "first");
    await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    await rm(path.join(bundledSkillsDir, "first"), { recursive: true });
    await createSkill(bundledSkillsDir, "second");
    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });

    const skillsDir = path.join(codexHome, "skills");
    expect(existsSync(path.join(skillsDir, "first"))).toBe(false);
    expect(existsSync(path.join(skillsDir, "second"))).toBe(true);
  });

  it("gives each task run an isolated dir, so concurrent runs never share", async () => {
    await createSkill(bundledSkillsDir, "query-data");

    const [homeA, homeB] = await Promise.all([
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-a",
        bundledSkillsDir,
        log: noopLog,
      }),
      prepareCodexHome({
        appDataPath,
        taskRunId: "run-b",
        bundledSkillsDir,
        log: noopLog,
      }),
    ]);

    expect(homeA).not.toBe(homeB);
    expect(existsSync(path.join(homeA, "skills", "query-data"))).toBe(true);
    expect(existsSync(path.join(homeB, "skills", "query-data"))).toBe(true);
  });

  it("cleanupCodexHome removes the run's dir and is a no-op when absent", async () => {
    await createSkill(bundledSkillsDir, "query-data");
    const codexHome = await prepareCodexHome({
      appDataPath,
      taskRunId,
      bundledSkillsDir,
      log: noopLog,
    });
    expect(existsSync(codexHome)).toBe(true);

    await cleanupCodexHome(appDataPath, taskRunId);
    expect(existsSync(codexHome)).toBe(false);
    expect(existsSync(getCodexHomeDir(appDataPath, taskRunId))).toBe(false);

    // Second call on a now-absent dir must not throw.
    await expect(
      cleanupCodexHome(appDataPath, taskRunId),
    ).resolves.toBeUndefined();
  });

  it("rejects an unsafe taskRunId instead of escaping the codex-home dir", async () => {
    const outside = path.join(appDataPath, "keep-me");
    await createSkill(outside, "precious");

    for (const badId of ["", ".", "..", "../../escape", "nested/evil"]) {
      expect(() => getCodexHomeDir(appDataPath, badId)).toThrow();
      await expect(
        prepareCodexHome({
          appDataPath,
          taskRunId: badId,
          bundledSkillsDir,
          log: noopLog,
        }),
      ).rejects.toThrow();
      await expect(cleanupCodexHome(appDataPath, badId)).rejects.toThrow();
    }

    expect(existsSync(path.join(outside, "precious", "SKILL.md"))).toBe(true);
  });
});
