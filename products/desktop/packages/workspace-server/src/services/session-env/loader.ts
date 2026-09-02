import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Matches the file naming convention used by Claude Agent SDK to write
 * SessionStart/Setup/CwdChanged/FileChanged hook output. The SDK reads files
 * matching this pattern under `<CLAUDE_CONFIG_DIR>/session-env/<sessionId>/`
 * and sources them before running its bash tool.
 *
 * Mirrors `ZI8` in @anthropic-ai/claude-agent-sdk/cli.js.
 */
const HOOK_FILE_RE =
  /^(setup|sessionstart|cwdchanged|filechanged)-hook-\d+\.sh$/;

/**
 * Bash-internal vars we never want to propagate to git/gh subprocesses — they
 * either have shell-only meaning or just add noise. Anything else that bash
 * produces but the parent didn't have is treated as a genuine override.
 */
const BASH_INTERNAL_VARS = new Set([
  "_",
  "BASHOPTS",
  "BASH_ARGC",
  "BASH_ARGV",
  "BASH_LINENO",
  "BASH_SOURCE",
  "BASH_VERSINFO",
  "BASH_VERSION",
  "DIRSTACK",
  "EUID",
  "GROUPS",
  "HOSTNAME",
  "HOSTTYPE",
  "IFS",
  "MACHTYPE",
  "OPTIND",
  "OSTYPE",
  "PIPESTATUS",
  "PPID",
  "PS1",
  "PS2",
  "PS3",
  "PS4",
  "PWD",
  "OLDPWD",
  "RANDOM",
  "SECONDS",
  "SHELLOPTS",
  "SHLVL",
  "UID",
]);

const PARSE_TIMEOUT_MS = 5000;

function shellSingleQuote(s: string): string {
  return `'${s.replace(/'/g, "'\\''")}'`;
}

/**
 * Load env-var overrides produced by Claude Agent SDK SessionStart-style
 * hooks for a given session.
 *
 * The SDK writes one `<event>-hook-<N>.sh` file per hook into
 * `<CLAUDE_CONFIG_DIR>/session-env/<sessionId>/`, each containing shell
 * `export VAR=value` lines (e.g. `export SSH_AUTH_SOCK=...` from a Secretive
 * code-signing hook). The SDK sources these into its bash subprocess before
 * each tool command. Mirroring that here lets git/gh commands triggered from
 * the UI see the same env — most importantly, the SSH_AUTH_SOCK that
 * Secretive's hook re-points at the Secretive agent for commit signing.
 *
 * Returns only the vars whose post-source value differs from the current
 * process env. Empty object if `CLAUDE_CONFIG_DIR` is unset, the session dir
 * does not exist, no hook files are present, or bash fails.
 */
export async function loadSessionEnvOverrides(
  sessionId: string,
): Promise<Record<string, string>> {
  const claudeConfigDir = process.env.CLAUDE_CONFIG_DIR;
  if (!claudeConfigDir) return {};

  const sessionDir = path.join(claudeConfigDir, "session-env", sessionId);

  let entries: string[];
  try {
    entries = await fs.readdir(sessionDir);
  } catch {
    return {};
  }

  const files = entries.filter((f) => HOOK_FILE_RE.test(f)).sort();
  if (files.length === 0) return {};

  const filePaths = files.map((f) => path.join(sessionDir, f));
  const sourceCmd = filePaths
    .map((p) => `. ${shellSingleQuote(p)} 2>/dev/null || true`)
    .join("; ");
  const cmd = `${sourceCmd}; env -0`;

  return new Promise((resolve) => {
    let settled = false;
    const finish = (overrides: Record<string, string>) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(overrides);
    };

    const timer = setTimeout(() => {
      try {
        proc.kill("SIGKILL");
      } catch {}
      finish({});
    }, PARSE_TIMEOUT_MS);

    const proc = spawn("bash", ["-c", cmd], {
      stdio: ["ignore", "pipe", "ignore"],
      env: process.env,
    });

    const chunks: Buffer[] = [];
    proc.stdout.on("data", (c) => chunks.push(c as Buffer));
    proc.on("error", () => {
      finish({});
    });
    proc.on("close", () => {
      const out = Buffer.concat(chunks).toString("utf8");
      const overrides: Record<string, string> = {};
      for (const entry of out.split("\0")) {
        if (!entry) continue;
        const eq = entry.indexOf("=");
        if (eq <= 0) continue;
        const key = entry.slice(0, eq);
        if (BASH_INTERNAL_VARS.has(key)) continue;
        const value = entry.slice(eq + 1);
        if (process.env[key] !== value) overrides[key] = value;
      }
      finish(overrides);
    });
  });
}
