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
 * `$HOME`, not `$CODEX_HOME`). The user's real `~/.codex/config.toml` is copied
 * in so their Codex configuration still applies without Windows symlink
 * privileges, minus its `mcp_servers` tables: PostHog sessions only get the MCP
 * servers PostHog injects per thread (see {@link stripMcpServers}).
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

  const privateConfig = path.join(codexHome, "config.toml");
  await fs.promises.rm(privateConfig, { force: true });
  const userConfig = path.join(os.homedir(), ".codex", "config.toml");
  if (fs.existsSync(userConfig)) {
    try {
      const config = await fs.promises.readFile(userConfig, "utf-8");
      await fs.promises.writeFile(privateConfig, stripMcpServers(config));
    } catch (err) {
      options.log.warn("Failed to copy codex config into codex home", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return codexHome;
}

const MCP_SERVERS_HEADER = /^\[\[?\s*mcp_servers\s*(?:[.\]])/;
const MCP_SERVERS_KEY = /^mcp_servers\s*[.=]/;

/**
 * Drops every `mcp_servers` definition from a codex config.toml: `[mcp_servers]`
 * and `[mcp_servers.<name>...]` tables with their bodies, and top-level
 * `mcp_servers.<name>... = ...` / `mcp_servers = {...}` keys. Everything else is
 * returned byte for byte.
 *
 * The user's own MCP servers must not run inside PostHog sessions (an
 * unauthenticated or broken one stalls every thread), and disabling them by
 * name with `-c mcp_servers.<name>.enabled=false` is worse than useless: a
 * per-thread `mcp_servers` override discards those flags, and a name without a
 * matching table in the loaded config yields a transport-less table that codex
 * rejects at startup.
 */
export function stripMcpServers(toml: string): string {
  const kept: string[] = [];
  let inMcpTable = false;
  let inTable = false;
  let openQuotes: string | null = null;
  let dropRestOfString = false;

  for (const line of toml.split("\n")) {
    // Inside a multiline string every line is content, so a `[mcp_servers` there
    // is prose. Reading it as a header would drop the closing delimiter and hand
    // codex a config it cannot parse.
    const inString = openQuotes !== null;
    const trimmed = line.trim();
    if (!inString && trimmed.startsWith("[")) {
      inTable = true;
      inMcpTable = MCP_SERVERS_HEADER.test(trimmed);
    }
    const drop: boolean = inString
      ? inMcpTable || dropRestOfString
      : inMcpTable || (!inTable && MCP_SERVERS_KEY.test(trimmed));

    openQuotes = advanceMultilineString(line, openQuotes);
    // A dropped key whose value opens a multiline string takes the whole value.
    dropRestOfString = drop && openQuotes !== null;
    if (!drop) kept.push(line);
  }
  return kept.join("\n");
}

/**
 * Returns the multiline-string delimiter still open at the end of `line`, or
 * null when the line ends outside one. `open` carries that state in.
 */
function advanceMultilineString(
  line: string,
  open: string | null,
): string | null {
  let quotes = open;
  for (let i = 0; i < line.length; i++) {
    if (quotes !== null) {
      if (line.startsWith(quotes, i)) {
        quotes = null;
        i += 2;
      }
      continue;
    }
    if (line.startsWith('"""', i) || line.startsWith("'''", i)) {
      quotes = line.slice(i, i + 3);
      i += 2;
      continue;
    }
    // A comment runs to the end of the line, so nothing after it opens a string.
    if (line[i] === "#") break;
  }
  return quotes;
}
