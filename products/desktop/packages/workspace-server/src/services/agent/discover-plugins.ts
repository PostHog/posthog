import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { SdkPluginConfig } from "@anthropic-ai/claude-agent-sdk";
import { getCodexSkillsDir } from "../posthog-plugin/codex-mirror";
import {
  findSkillDirs,
  getMarketplaceInstallPaths,
  getUserSkillsDir,
  linkSkillsInto,
} from "../skills/skill-discovery";
import type { AgentScopedLogger } from "./ports";

interface DiscoverPluginsOptions {
  userDataDir: string;
  repoPath?: string;
  /**
   * The bundled PostHog skills dir (`<plugin>/skills`). Used only to dedupe the
   * user's Codex skills against names PostHog already provides.
   */
  bundledSkillsDir?: string;
}

const noopLogger: AgentScopedLogger = {
  debug() {},
  info() {},
  warn() {},
  error() {},
};

export async function discoverExternalPlugins(
  options: DiscoverPluginsOptions,
  log: AgentScopedLogger = noopLogger,
): Promise<SdkPluginConfig[]> {
  const [globalSkills, marketplacePlugins, repoSkills, codexSkills] =
    await Promise.all([
      discoverUserSkills(options.userDataDir, log),
      discoverMarketplacePlugins(),
      options.repoPath
        ? discoverRepoSkills(options.userDataDir, options.repoPath, log)
        : Promise.resolve([]),
      discoverCodexSkills(options.userDataDir, options.bundledSkillsDir, log),
    ]);

  return [
    ...globalSkills,
    ...marketplacePlugins,
    ...repoSkills,
    ...codexSkills,
  ];
}

/**
 * Surfaces the user's own Codex skills (`~/.agents/skills`) in Claude sessions
 * too — the symmetric half of the cross-harness merge. Names already provided
 * by PostHog (bundled catalog) or the user's `~/.claude/skills` are
 * skipped so a skill never loads twice under different plugins.
 */
async function discoverCodexSkills(
  userDataDir: string,
  bundledSkillsDir: string | undefined,
  log: AgentScopedLogger,
): Promise<SdkPluginConfig[]> {
  const [userNames, bundledNames] = await Promise.all([
    findSkillDirs(getUserSkillsDir()),
    bundledSkillsDir ? findSkillDirs(bundledSkillsDir) : Promise.resolve([]),
  ]);
  const exclude = new Set([...userNames, ...bundledNames]);

  return buildSyntheticPlugin(
    getCodexSkillsDir(),
    path.join(userDataDir, "plugins", "codex-skills"),
    "codex-skills",
    "User Codex skills",
    log,
    exclude,
  );
}

async function discoverUserSkills(
  userDataDir: string,
  log: AgentScopedLogger,
): Promise<SdkPluginConfig[]> {
  return buildSyntheticPlugin(
    getUserSkillsDir(),
    path.join(userDataDir, "plugins", "user-skills"),
    "user-skills",
    "User Claude skills",
    log,
  );
}

async function discoverMarketplacePlugins(): Promise<SdkPluginConfig[]> {
  const paths = await getMarketplaceInstallPaths();
  return paths.map((p) => ({ type: "local" as const, path: p }));
}

async function discoverRepoSkills(
  userDataDir: string,
  repoPath: string,
  log: AgentScopedLogger,
): Promise<SdkPluginConfig[]> {
  const skillsDir = path.join(repoPath, ".claude", "skills");
  const hash = crypto
    .createHash("md5")
    .update(repoPath)
    .digest("hex")
    .slice(0, 8);

  return buildSyntheticPlugin(
    skillsDir,
    path.join(userDataDir, "plugins", `repo-skills-${hash}`),
    `repo-skills-${hash}`,
    `Repo skills for ${path.basename(repoPath)}`,
    log,
  );
}

async function buildSyntheticPlugin(
  sourceSkillsDir: string,
  pluginDir: string,
  name: string,
  description: string,
  log: AgentScopedLogger,
  exclude?: Set<string>,
): Promise<SdkPluginConfig[]> {
  try {
    const allSkillDirs = await findSkillDirs(sourceSkillsDir);
    const skillDirs = allSkillDirs.filter(
      (skillName) => !exclude?.has(skillName),
    );
    if (skillDirs.length === 0) {
      return [];
    }

    const syntheticSkillsDir = path.join(pluginDir, "skills");
    await fs.promises.mkdir(syntheticSkillsDir, { recursive: true });

    await fs.promises.writeFile(
      path.join(pluginDir, "plugin.json"),
      JSON.stringify({ name, description, version: "1.0.0" }),
    );

    try {
      const existing = await fs.promises.readdir(syntheticSkillsDir);
      await Promise.all(
        existing.map((e) =>
          fs.promises.rm(path.join(syntheticSkillsDir, e), {
            recursive: true,
            force: true,
          }),
        ),
      );
    } catch {
      // ignore
    }

    await linkSkillsInto(syntheticSkillsDir, sourceSkillsDir, skillDirs, log);

    return [{ type: "local", path: pluginDir }];
  } catch (err) {
    log.warn("Failed to discover skills", {
      source: sourceSkillsDir,
      error: err instanceof Error ? err.message : String(err),
    });
    return [];
  }
}
