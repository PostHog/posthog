import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { findSkillDirs, isSafePathSegment } from "../skills/skill-discovery";

const MIRROR_STATE_FILE = ".posthog-mirror.json";

export interface CodexMirrorState {
  version: number;
  /** Skill directory names in ~/.agents/skills that we put there. */
  mirrored: string[];
}

/**
 * The shared, cross-agent skills directory that Codex (and other tools) read.
 * PostHog never writes skills here — it only reads it to surface the
 * user's own Codex skills in the Skills tab. Bundled and Claude skills reach
 * Codex sessions through a private CODEX_HOME instead, so this directory stays
 * the user's own.
 */
export function getCodexSkillsDir(): string {
  return path.join(os.homedir(), ".agents", "skills");
}

export async function readCodexMirrorState(
  codexDir: string,
): Promise<CodexMirrorState> {
  try {
    const content = await fs.promises.readFile(
      path.join(codexDir, MIRROR_STATE_FILE),
      "utf-8",
    );
    const data = JSON.parse(content) as CodexMirrorState;
    if (!Array.isArray(data.mirrored)) {
      return { version: 1, mirrored: [] };
    }
    return {
      version: 1,
      mirrored: data.mirrored.filter(isSafePathSegment),
    };
  } catch {
    return { version: 1, mirrored: [] };
  }
}

async function readSkillManifest(skillDir: string): Promise<Buffer | null> {
  try {
    return await fs.promises.readFile(path.join(skillDir, "SKILL.md"));
  } catch {
    return null;
  }
}

/**
 * One-time cleanup of the skills earlier builds copied into the shared
 * ~/.agents/skills directory (the bundled catalog via the old `syncCodexSkills`,
 * and the user's own skills via the old mirror). Both are gone now; this
 * removes their leftovers so the directory is the user's own again.
 *
 * Safety: only deletes skills we can prove we wrote.
 * - Names recorded in `.posthog-mirror.json` were copies of the user's
 *   `~/.claude/skills`; the originals still live there, so the copy is safe to drop.
 * - A bundled-catalog leftover is identified by an exact name match against the
 *   current bundled skills *and* a byte-identical `SKILL.md`. The content check
 *   guarantees we never delete a user's own Codex skill that merely shares a name.
 *
 * Returns the directory names that were removed.
 */
export async function cleanupLegacyCodexMirror(
  codexDir: string,
  bundledSkillsDir: string,
): Promise<string[]> {
  if (!fs.existsSync(codexDir)) {
    return [];
  }

  const removed = new Set<string>();

  const remove = async (name: string): Promise<void> => {
    await fs.promises.rm(path.join(codexDir, name), {
      recursive: true,
      force: true,
    });
    removed.add(name);
  };

  // 1. Tracked copies of the user's own skills.
  const state = await readCodexMirrorState(codexDir);
  for (const name of state.mirrored) {
    if (fs.existsSync(path.join(codexDir, name))) {
      await remove(name);
    }
  }

  // 2. Bundled-catalog copies: same name and byte-identical SKILL.md.
  const bundledNames = await findSkillDirs(bundledSkillsDir);
  await Promise.all(
    bundledNames.map(async (name) => {
      if (removed.has(name)) return;
      const target = path.join(codexDir, name);
      if (!fs.existsSync(target)) return;
      const [bundled, present] = await Promise.all([
        readSkillManifest(path.join(bundledSkillsDir, name)),
        readSkillManifest(target),
      ]);
      if (bundled && present && bundled.equals(present)) {
        await remove(name);
      }
    }),
  );

  // 3. Drop the legacy mirror-state file.
  await fs.promises.rm(path.join(codexDir, MIRROR_STATE_FILE), { force: true });

  return [...removed];
}
