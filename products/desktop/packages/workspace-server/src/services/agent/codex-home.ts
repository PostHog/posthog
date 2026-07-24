import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  findSkillDirs,
  getUserSkillsDir,
  isSafePathSegment,
  linkSkillsInto,
} from "../skills/skill-discovery";
import type { AgentScopedLogger } from "./ports";

/**
 * Resolves a task run's private CODEX_HOME directory. Each run gets its own so
 * concurrent Codex sessions never share — and never race to rebuild — the same
 * skills directory.
 */
export function getCodexHomeDir(
  appDataPath: string,
  taskRunId: string,
): string {
  if (!isSafePathSegment(taskRunId)) {
    throw new Error(`Unsafe taskRunId: ${JSON.stringify(taskRunId)}`);
  }
  return path.join(appDataPath, "codex-home", taskRunId);
}

/**
 * Removes a task run's private CODEX_HOME. Safe for any adapter — a no-op when
 * the directory was never created.
 */
export async function cleanupCodexHome(
  appDataPath: string,
  taskRunId: string,
): Promise<void> {
  await fs.promises.rm(getCodexHomeDir(appDataPath, taskRunId), {
    recursive: true,
    force: true,
  });
}

/**
 * Builds a private CODEX_HOME for PostHog's own Codex sessions, so they
 * load the bundled PostHog catalog and the user's `~/.claude/skills` — without
 * ever writing into the shared cross-agent `~/.agents/skills`.
 *
 * codex scans `$CODEX_HOME/skills` plus `$HOME/.agents/skills`. By pointing
 * CODEX_HOME at this app-private dir we feed our skills through the former while
 * the user's own Codex skills still load from the latter (it is keyed off
 * `$HOME`, not `$CODEX_HOME`). The user's real `~/.codex/config.toml` is
 * symlinked in so their Codex configuration still applies.
 *
 * Returns the CODEX_HOME path to hand to the spawned process.
 */
export async function prepareCodexHome(options: {
  appDataPath: string;
  taskRunId: string;
  bundledSkillsDir: string;
  log: AgentScopedLogger;
}): Promise<string> {
  const codexHome = getCodexHomeDir(options.appDataPath, options.taskRunId);
  const skillsDir = path.join(codexHome, "skills");

  // A retried run reuses its taskRunId, so wipe any stale links before rebuilding.
  await fs.promises.rm(skillsDir, { recursive: true, force: true });
  await fs.promises.mkdir(skillsDir, { recursive: true });

  // Bundled catalog first, then the user's Claude skills. Bundled wins on a
  // name collision so the curated catalog is never shadowed.
  const sources = [options.bundledSkillsDir, getUserSkillsDir()];
  const linked = new Set<string>();
  for (const sourceDir of sources) {
    const names = (await findSkillDirs(sourceDir)).filter(
      (name) => !linked.has(name),
    );
    const ok = await linkSkillsInto(skillsDir, sourceDir, names, options.log);
    for (const name of ok) linked.add(name);
  }

  const configLink = path.join(codexHome, "config.toml");
  await fs.promises.rm(configLink, { force: true });
  const userConfig = path.join(os.homedir(), ".codex", "config.toml");
  if (fs.existsSync(userConfig)) {
    try {
      await fs.promises.symlink(
        await fs.promises.realpath(userConfig),
        configLink,
      );
    } catch (err) {
      options.log.warn("Failed to link codex config into codex home", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return codexHome;
}
