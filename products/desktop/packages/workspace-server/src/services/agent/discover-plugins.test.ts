import { vol } from "memfs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("node:fs", async () => {
  const { fs } = await import("memfs");
  return { ...fs, default: fs };
});

vi.mock("node:fs/promises", async () => {
  const { fs } = await import("memfs");
  return { ...fs.promises, default: fs.promises };
});

vi.mock("node:os", () => ({
  homedir: () => "/mock/home",
  tmpdir: () => "/mock/tmp",
  default: { homedir: () => "/mock/home", tmpdir: () => "/mock/tmp" },
}));

import { discoverExternalPlugins } from "./discover-plugins";

const USER_DATA_DIR = "/mock/userData";
const USER_SKILLS_DIR = "/mock/home/.claude/skills";
const INSTALLED_PLUGINS_PATH =
  "/mock/home/.claude/plugins/installed_plugins.json";

function createSkillDir(basePath: string, skillName: string) {
  const skillPath = `${basePath}/${skillName}`;
  vol.mkdirSync(skillPath, { recursive: true });
  vol.writeFileSync(`${skillPath}/SKILL.md`, `# ${skillName}`);
}

describe("discoverExternalPlugins", () => {
  beforeEach(() => {
    vol.reset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns empty array when no skills or plugins exist", async () => {
    const result = await discoverExternalPlugins({
      userDataDir: USER_DATA_DIR,
    });
    expect(result).toEqual([]);
  });

  describe("user skills", () => {
    it("discovers user skills from ~/.claude/skills/", async () => {
      createSkillDir(USER_SKILLS_DIR, "my-skill");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        type: "local",
        path: `${USER_DATA_DIR}/plugins/user-skills`,
      });
    });

    it("creates a synthetic plugin.json for user skills", async () => {
      createSkillDir(USER_SKILLS_DIR, "my-skill");

      await discoverExternalPlugins({ userDataDir: USER_DATA_DIR });

      const pluginJson = JSON.parse(
        vol.readFileSync(
          `${USER_DATA_DIR}/plugins/user-skills/plugin.json`,
          "utf-8",
        ) as string,
      );
      expect(pluginJson).toEqual({
        name: "user-skills",
        description: "User Claude skills",
        version: "1.0.0",
      });
    });

    it("symlinks each skill directory into the synthetic plugin", async () => {
      createSkillDir(USER_SKILLS_DIR, "skill-a");
      createSkillDir(USER_SKILLS_DIR, "skill-b");

      await discoverExternalPlugins({ userDataDir: USER_DATA_DIR });

      const syntheticSkillsDir = `${USER_DATA_DIR}/plugins/user-skills/skills`;
      const entries = vol.readdirSync(syntheticSkillsDir);
      expect(entries).toContain("skill-a");
      expect(entries).toContain("skill-b");
    });

    it("ignores directories without SKILL.md", async () => {
      vol.mkdirSync(`${USER_SKILLS_DIR}/not-a-skill`, { recursive: true });
      vol.writeFileSync(`${USER_SKILLS_DIR}/not-a-skill/README.md`, "nope");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("ignores regular files in the skills directory", async () => {
      vol.mkdirSync(USER_SKILLS_DIR, { recursive: true });
      vol.writeFileSync(`${USER_SKILLS_DIR}/random-file.txt`, "hello");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("cleans stale symlinks before creating new ones", async () => {
      createSkillDir(USER_SKILLS_DIR, "fresh-skill");

      // First run
      await discoverExternalPlugins({ userDataDir: USER_DATA_DIR });

      // Manually add a stale entry to simulate leftover from previous run
      const syntheticSkillsDir = `${USER_DATA_DIR}/plugins/user-skills/skills`;
      vol.mkdirSync(`${syntheticSkillsDir}/stale-skill`, { recursive: true });

      // Second run should clean stale and only have fresh-skill
      await discoverExternalPlugins({ userDataDir: USER_DATA_DIR });

      const entries = vol.readdirSync(syntheticSkillsDir);
      expect(entries).toEqual(["fresh-skill"]);
    });
  });

  describe("marketplace plugins", () => {
    it("discovers installed marketplace plugins", async () => {
      const installPath = "/mock/plugins/my-plugin";
      vol.mkdirSync(installPath, { recursive: true });

      const installedPlugins = {
        version: 1,
        plugins: {
          "my-plugin": [{ scope: "global", installPath, version: "1.0.0" }],
        },
      };

      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify(installedPlugins),
      );

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([{ type: "local", path: installPath }]);
    });

    it("skips plugins whose installPath does not exist", async () => {
      const installedPlugins = {
        version: 1,
        plugins: {
          "missing-plugin": [
            {
              scope: "global",
              installPath: "/nonexistent/path",
              version: "1.0.0",
            },
          ],
        },
      };

      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify(installedPlugins),
      );

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("returns empty when installed_plugins.json is missing", async () => {
      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("returns empty when installed_plugins.json has invalid JSON", async () => {
      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(INSTALLED_PLUGINS_PATH, "not json at all");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("returns empty when plugins field is missing", async () => {
      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(INSTALLED_PLUGINS_PATH, JSON.stringify({ version: 1 }));

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("skips non-array plugin entries", async () => {
      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify({
          version: 1,
          plugins: { "bad-entry": "not-an-array" },
        }),
      );

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([]);
    });

    it("excludes the posthog marketplace plugin (bundled in-app)", async () => {
      const posthogPath = "/mock/plugins/posthog";
      const otherPath = "/mock/plugins/other";
      vol.mkdirSync(posthogPath, { recursive: true });
      vol.mkdirSync(otherPath, { recursive: true });

      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify({
          version: 2,
          plugins: {
            "posthog@claude-plugins-official": [
              { scope: "user", installPath: posthogPath, version: "1.0.0" },
            ],
            "other@claude-plugins-official": [
              { scope: "user", installPath: otherPath, version: "1.0.0" },
            ],
          },
        }),
      );

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([{ type: "local", path: otherPath }]);
    });

    it("handles multiple plugins with multiple entries", async () => {
      const pathA = "/mock/plugins/plugin-a";
      const pathB = "/mock/plugins/plugin-b";
      vol.mkdirSync(pathA, { recursive: true });
      vol.mkdirSync(pathB, { recursive: true });

      const installedPlugins = {
        version: 1,
        plugins: {
          "plugin-a": [
            { scope: "global", installPath: pathA, version: "1.0.0" },
          ],
          "plugin-b": [
            { scope: "global", installPath: pathB, version: "2.0.0" },
          ],
        },
      };

      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify(installedPlugins),
      );

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toHaveLength(2);
      expect(result).toContainEqual({ type: "local", path: pathA });
      expect(result).toContainEqual({ type: "local", path: pathB });
    });
  });

  describe("repo skills", () => {
    const REPO_PATH = "/mock/repo";

    it("discovers skills from repo .claude/skills/", async () => {
      createSkillDir(`${REPO_PATH}/.claude/skills`, "repo-skill");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath: REPO_PATH,
      });

      expect(result).toHaveLength(1);
      expect(result[0]?.type).toBe("local");
      expect(result[0]?.path).toMatch(
        /\/mock\/userData\/plugins\/repo-skills-[a-f0-9]{8}$/,
      );
    });

    it("creates a synthetic plugin.json with repo name in description", async () => {
      createSkillDir(`${REPO_PATH}/.claude/skills`, "repo-skill");

      await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath: REPO_PATH,
      });

      // Find the generated plugin dir
      const pluginEntries = vol.readdirSync(
        `${USER_DATA_DIR}/plugins`,
      ) as string[];
      const repoPluginDir = pluginEntries.find((e) =>
        e.startsWith("repo-skills-"),
      );
      expect(repoPluginDir).toBeDefined();

      const pluginJson = JSON.parse(
        vol.readFileSync(
          `${USER_DATA_DIR}/plugins/${repoPluginDir}/plugin.json`,
          "utf-8",
        ) as string,
      );
      expect(pluginJson.description).toBe("Repo skills for repo");
    });

    it("returns empty when repoPath has no .claude/skills dir", async () => {
      vol.mkdirSync(REPO_PATH, { recursive: true });

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath: REPO_PATH,
      });

      expect(result).toEqual([]);
    });

    it("skips repo skills when repoPath is not provided", async () => {
      createSkillDir(`${REPO_PATH}/.claude/skills`, "repo-skill");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      // Only user skills and marketplace plugins are checked
      expect(result).toEqual([]);
    });

    it("uses deterministic hash for repo plugin dir name", async () => {
      createSkillDir(`${REPO_PATH}/.claude/skills`, "repo-skill");

      const result1 = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath: REPO_PATH,
      });

      vol.reset();
      createSkillDir(`${REPO_PATH}/.claude/skills`, "repo-skill");

      const result2 = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath: REPO_PATH,
      });

      expect(result1[0]?.path).toBe(result2[0]?.path);
    });
  });

  describe("combined sources", () => {
    it("merges all three sources together", async () => {
      // User skills
      createSkillDir(USER_SKILLS_DIR, "user-skill");

      // Marketplace plugin
      const marketplacePath = "/mock/plugins/marketplace-plugin";
      vol.mkdirSync(marketplacePath, { recursive: true });
      vol.mkdirSync("/mock/home/.claude/plugins", { recursive: true });
      vol.writeFileSync(
        INSTALLED_PLUGINS_PATH,
        JSON.stringify({
          version: 1,
          plugins: {
            mp: [
              {
                scope: "global",
                installPath: marketplacePath,
                version: "1.0.0",
              },
            ],
          },
        }),
      );

      // Repo skills
      const repoPath = "/mock/repo";
      createSkillDir(`${repoPath}/.claude/skills`, "repo-skill");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        repoPath,
      });

      expect(result).toHaveLength(3);
      expect(result[0]).toEqual({
        type: "local",
        path: `${USER_DATA_DIR}/plugins/user-skills`,
      });
      expect(result[1]).toEqual({
        type: "local",
        path: marketplacePath,
      });
      expect(result[2]?.type).toBe("local");
      expect(result[2]?.path).toMatch(/repo-skills-/);
    });
  });

  describe("codex skills", () => {
    const CODEX_SKILLS_DIR = "/mock/home/.agents/skills";

    it("discovers the user's codex skills as a synthetic plugin", async () => {
      createSkillDir(CODEX_SKILLS_DIR, "codex-skill");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result).toEqual([
        { type: "local", path: `${USER_DATA_DIR}/plugins/codex-skills` },
      ]);
      const pluginJson = JSON.parse(
        vol.readFileSync(
          `${USER_DATA_DIR}/plugins/codex-skills/plugin.json`,
          "utf-8",
        ) as string,
      );
      expect(pluginJson.description).toBe("User Codex skills");
    });

    it("excludes codex skills whose name matches a user skill", async () => {
      createSkillDir(USER_SKILLS_DIR, "shared");
      createSkillDir(CODEX_SKILLS_DIR, "shared");
      createSkillDir(CODEX_SKILLS_DIR, "codex-only");

      await discoverExternalPlugins({ userDataDir: USER_DATA_DIR });

      const entries = vol.readdirSync(
        `${USER_DATA_DIR}/plugins/codex-skills/skills`,
      );
      expect(entries).toEqual(["codex-only"]);
    });

    it("excludes codex skills whose name matches a bundled skill", async () => {
      const bundledSkillsDir = "/mock/bundled/skills";
      createSkillDir(bundledSkillsDir, "query-data");
      createSkillDir(CODEX_SKILLS_DIR, "query-data");
      createSkillDir(CODEX_SKILLS_DIR, "codex-only");

      await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
        bundledSkillsDir,
      });

      const entries = vol.readdirSync(
        `${USER_DATA_DIR}/plugins/codex-skills/skills`,
      );
      expect(entries).toEqual(["codex-only"]);
    });

    it("omits the codex plugin entirely when every name collides", async () => {
      createSkillDir(USER_SKILLS_DIR, "dup");
      createSkillDir(CODEX_SKILLS_DIR, "dup");

      const result = await discoverExternalPlugins({
        userDataDir: USER_DATA_DIR,
      });

      expect(result.some((p) => p.path.endsWith("/codex-skills"))).toBe(false);
    });
  });
});
