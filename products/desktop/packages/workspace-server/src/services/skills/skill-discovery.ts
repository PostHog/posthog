import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parseSkillFrontmatter } from "./parse-skill-frontmatter";
import type { SkillFileEntry, SkillInfo, SkillSource } from "./schemas";

interface InstalledPluginEntry {
  scope: string;
  installPath: string;
  version: string;
}

interface InstalledPluginsFile {
  version: number;
  plugins: Record<string, InstalledPluginEntry[]>;
}

/** Sources whose directories we own on the user's behalf and may mutate. */
export function isEditableSource(source: SkillSource): boolean {
  return source === "user" || source === "repo";
}

/** The user-level skills root (`~/.claude/skills`), owned by us. */
export function getUserSkillsDir(): string {
  return path.join(os.homedir(), ".claude", "skills");
}

/**
 * True when `value` is a single path segment safe to join onto a trusted
 * directory. Rejects "", ".", "..", and anything containing a separator, so a
 * value from a state file or an RPC boundary can never widen a `path.join`
 * into a sibling or parent directory (and a recursive delete along with it).
 */
export function isSafePathSegment(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value !== "." &&
    value !== ".." &&
    !value.includes("/") &&
    !value.includes("\\")
  );
}

/** Heuristic: content with NUL bytes in the first 4 KiB is binary. */
export function isProbablyText(bytes: Uint8Array): boolean {
  return !bytes.subarray(0, 4096).includes(0);
}

export async function findSkillDirs(
  sourceSkillsDir: string,
): Promise<string[]> {
  if (!fs.existsSync(sourceSkillsDir)) {
    return [];
  }

  const entries = await fs.promises.readdir(sourceSkillsDir, {
    withFileTypes: true,
  });

  return entries
    .filter(
      (e) =>
        (e.isDirectory() || e.isSymbolicLink()) &&
        // Hidden dirs are never skills (also hides install staging dirs).
        !e.name.startsWith(".") &&
        fs.existsSync(path.join(sourceSkillsDir, e.name, "SKILL.md")),
    )
    .map((e) => e.name);
}

/**
 * Symlinks each named skill from `sourceDir` into `targetDir`, resolving the
 * real path first so the link works even when the source is itself a symlink.
 * Failures are logged and skipped. Returns the names that were linked.
 */
export async function linkSkillsInto(
  targetDir: string,
  sourceDir: string,
  skillNames: string[],
  log: { warn: (message: string, meta?: Record<string, unknown>) => void },
): Promise<string[]> {
  const linked: string[] = [];
  await Promise.all(
    skillNames.map(async (skillName) => {
      try {
        const realSrc = await fs.promises.realpath(
          path.join(sourceDir, skillName),
        );
        await fs.promises.symlink(realSrc, path.join(targetDir, skillName));
        linked.push(skillName);
      } catch (err) {
        log.warn("Failed to symlink skill", {
          skillName,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }),
  );
  return linked;
}

export async function getMarketplaceInstallPaths(): Promise<string[]> {
  const installedPath = path.join(
    os.homedir(),
    ".claude",
    "plugins",
    "installed_plugins.json",
  );

  try {
    const content = await fs.promises.readFile(installedPath, "utf-8");
    const data = JSON.parse(content) as InstalledPluginsFile;

    if (!data.plugins || typeof data.plugins !== "object") {
      return [];
    }

    const paths: string[] = [];
    for (const [key, entries] of Object.entries(data.plugins)) {
      if (!Array.isArray(entries)) continue;
      // Skip the marketplace posthog plugin — the app bundles its own.
      if (key.split("@")[0] === "posthog") continue;
      for (const entry of entries) {
        if (entry.installPath && fs.existsSync(entry.installPath)) {
          paths.push(entry.installPath);
        }
      }
    }
    return paths;
  } catch {
    return [];
  }
}

/**
 * Recursively lists regular files inside a skill directory. Symlinks are
 * skipped so a crafted skill cannot expose files outside its directory.
 */
export async function listSkillFiles(
  skillDir: string,
  maxFiles: number,
): Promise<SkillFileEntry[]> {
  const files: SkillFileEntry[] = [];

  const walk = async (dir: string, prefix: string): Promise<void> => {
    const entries = await fs.promises.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (files.length >= maxFiles) return;
      const relPath = prefix ? `${prefix}/${entry.name}` : entry.name;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath, relPath);
      } else if (entry.isFile()) {
        const stat = await fs.promises.stat(fullPath);
        files.push({ path: relPath, size: stat.size });
      }
    }
  };

  await walk(skillDir, "");
  return files.sort((a, b) => {
    // The manifest always leads; everything else is alphabetical.
    if (a.path === "SKILL.md") return -1;
    if (b.path === "SKILL.md") return 1;
    return a.path.localeCompare(b.path);
  });
}

export async function readSkillMetadataFromDir(
  skillsDir: string,
  source: SkillSource,
  repoName?: string,
): Promise<SkillInfo[]> {
  const skillNames = await findSkillDirs(skillsDir);
  if (skillNames.length === 0) return [];

  const results = await Promise.all(
    skillNames.map(async (skillName) => {
      const skillPath = path.join(skillsDir, skillName);
      try {
        const content = await fs.promises.readFile(
          path.join(skillPath, "SKILL.md"),
          "utf-8",
        );
        const frontmatter = parseSkillFrontmatter(content);
        return {
          name: frontmatter?.name ?? skillName,
          description: frontmatter?.description ?? "",
          source,
          path: skillPath,
          ...(repoName ? { repoName } : {}),
          editable: isEditableSource(source),
          skillMdBytes: Buffer.byteLength(content, "utf-8"),
        } satisfies SkillInfo;
      } catch {
        return null;
      }
    }),
  );
  return results.filter((r): r is SkillInfo => r !== null);
}
