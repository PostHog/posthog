import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { FoldersService } from "../folders/folders";
import { OnboardingImportServiceImpl } from "./onboarding-import";

let home: string;
let originalHome: string | undefined;

const emptyFolders = {
  getFolders: async () => [],
} as unknown as FoldersService;

async function writeJson(file: string, data: unknown) {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(data));
}

async function createUserSkill(name: string) {
  const skillPath = path.join(home, ".claude", "skills", name);
  await mkdir(skillPath, { recursive: true });
  await writeFile(
    path.join(skillPath, "SKILL.md"),
    `---\nname: ${name}\ndescription: a ${name} skill\n---\n`,
  );
}

beforeEach(async () => {
  home = await mkdtemp(path.join(tmpdir(), "onboarding-import-test-"));
  originalHome = process.env.HOME;
  process.env.HOME = home;
});

afterEach(async () => {
  process.env.HOME = originalHome;
  await rm(home, { recursive: true, force: true });
});

describe("OnboardingImportServiceImpl.getSummary", () => {
  it("returns zeroes when nothing is configured", async () => {
    const service = new OnboardingImportServiceImpl(emptyFolders);
    const summary = await service.getSummary();
    expect(summary).toEqual({
      total: 0,
      skills: { count: 0, paths: [] },
      plugins: { count: 0, paths: [] },
      mcpServers: { count: 0, paths: [] },
      permissions: { count: 0, paths: [] },
    });
  });

  it("counts user skills, mcp servers, and permission rules", async () => {
    await createUserSkill("alpha");
    await createUserSkill("beta");
    await writeJson(path.join(home, ".claude.json"), {
      mcpServers: { one: {}, two: {} },
    });
    await writeJson(path.join(home, ".claude", "settings.json"), {
      permissions: { allow: ["a", "b"], deny: ["c"] },
    });

    const service = new OnboardingImportServiceImpl(emptyFolders);
    const summary = await service.getSummary();

    expect(summary.skills.count).toBe(2);
    expect(summary.skills.paths).toEqual(["~/.claude/skills"]);
    expect(summary.mcpServers.count).toBe(2);
    expect(summary.mcpServers.paths).toEqual(["~/.claude.json"]);
    expect(summary.permissions.count).toBe(3);
    expect(summary.permissions.paths).toEqual(["~/.claude/settings.json"]);
    expect(summary.total).toBe(7);
  });

  it("ignores malformed config files", async () => {
    await mkdir(path.join(home, ".claude"), { recursive: true });
    await writeFile(path.join(home, ".claude.json"), "not json");
    await writeFile(path.join(home, ".claude", "settings.json"), "{ bad");

    const service = new OnboardingImportServiceImpl(emptyFolders);
    const summary = await service.getSummary();

    expect(summary.mcpServers.count).toBe(0);
    expect(summary.permissions.count).toBe(0);
    expect(summary.total).toBe(0);
  });
});
