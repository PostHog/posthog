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
 * Empties a task run's private CODEX_HOME except `sessions/`, the thread
 * rollouts `thread/resume` needs after the app relaunches. Safe for any
 * adapter — a no-op when the directory was never created.
 */
export async function cleanupCodexHome(
  appDataPath: string,
  taskRunId: string,
): Promise<void> {
  const codexHome = getCodexHomeDir(appDataPath, taskRunId);
  // `readdir` resolves through a link, so deleting entry by entry would empty
  // whatever a link at this path points at. Remove the link itself instead.
  const stats = await fs.promises.lstat(codexHome).catch(() => null);
  if (stats === null) return;
  if (!stats.isDirectory()) {
    await fs.promises.rm(codexHome, { recursive: true, force: true });
    return;
  }
  let entries: string[];
  try {
    entries = await fs.promises.readdir(codexHome);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry === "sessions") continue;
    await fs.promises.rm(path.join(codexHome, entry), {
      recursive: true,
      force: true,
    });
  }
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
      // The copy can still carry provider headers and environment values, and
      // it lands in a world-readable directory, so keep it to the owner.
      await fs.promises.writeFile(privateConfig, stripMcpServers(config), {
        mode: 0o600,
      });
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
  let value: OpenValue = { fence: null, depth: 0 };
  let dropRestOfValue = false;

  for (const line of toml.split("\n")) {
    // A line only carries structure when no value from an earlier line is still
    // open. Otherwise it is content, and a `[mcp_servers` there is prose — reading
    // it as a table header would hand codex a config it cannot parse.
    const structural = value.fence === null && value.depth === 0;
    const trimmed = line.trim();
    if (structural && trimmed.startsWith("[")) {
      inTable = true;
      inMcpTable = MCP_SERVERS_HEADER.test(trimmed);
    }
    const drop: boolean = structural
      ? inMcpTable || (!inTable && MCP_SERVERS_KEY.test(trimmed))
      : inMcpTable || dropRestOfValue;

    value = scanLine(line, value);
    // A dropped key whose value wraps onto later lines takes the whole value.
    dropRestOfValue = drop && (value.fence !== null || value.depth > 0);
    if (!drop) kept.push(line);
  }
  return kept.join("\n");
}

/**
 * A value left open at a line break: the multiline-string delimiter still to be
 * closed, and how many `[` or `{` are still unclosed.
 */
interface OpenValue {
  fence: string | null;
  depth: number;
}

/** Returns the value left open at the end of `line`, given the one open at its start. */
function scanLine(line: string, open: OpenValue): OpenValue {
  let { fence, depth } = open;
  for (let i = 0; i < line.length; i++) {
    if (fence !== null) {
      if (line.startsWith(fence, i)) {
        fence = null;
        i += 2;
      }
      continue;
    }
    if (line.startsWith('"""', i) || line.startsWith("'''", i)) {
      fence = line.slice(i, i + 3);
      i += 2;
    } else if (line[i] === '"' || line[i] === "'") {
      i = endOfString(line, i);
    } else if (line[i] === "#") {
      break; // A comment runs to the end of the line.
    } else if (line[i] === "[" || line[i] === "{") {
      depth += 1;
    } else if (line[i] === "]" || line[i] === "}") {
      depth = Math.max(0, depth - 1);
    }
  }
  return { fence, depth };
}

/**
 * Returns the index of the quote closing the single-line string that opens at
 * `start`, or the end of the line when it is never closed.
 */
function endOfString(line: string, start: number): number {
  const quote = line[start];
  for (let i = start + 1; i < line.length; i++) {
    // Only basic strings take backslash escapes; literal ones are verbatim.
    if (quote === '"' && line[i] === "\\") {
      i += 1;
      continue;
    }
    if (line[i] === quote) return i;
  }
  return line.length;
}
