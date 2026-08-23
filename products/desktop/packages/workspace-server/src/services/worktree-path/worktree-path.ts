import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import path from "node:path";

/**
 * Resolves a worktree's on-disk path. Prefers the current layout
 * (`<base>/<name>/<repo>`) and falls back to the legacy `<base>/<repo>/<name>`.
 * Checks disk rather than the name: names are now slugs, not numbers.
 */
export function deriveWorktreePath(
  worktreeBasePath: string,
  folderPath: string,
  worktreeName: string,
): string {
  const repoName = path.basename(folderPath);

  const newFormatPath = path.join(worktreeBasePath, worktreeName, repoName);
  const legacyFormatPath = path.join(worktreeBasePath, repoName, worktreeName);

  if (fs.existsSync(newFormatPath)) return newFormatPath;
  if (fs.existsSync(legacyFormatPath)) return legacyFormatPath;
  return newFormatPath;
}

/**
 * Removes the app-managed wrapper directory (`<base>/<name>`) around a
 * just-deleted worktree. Refuses anything that is not a direct child of the
 * configured base: an adopted external checkout's parent belongs to the user
 * and often holds the main repository itself. Uses `rmdir`, not recursive
 * removal, so even a containment bug could not delete more than one empty
 * directory.
 */
export async function removeManagedWorktreeWrapper(
  worktreePath: string,
  worktreeBasePath: string,
): Promise<boolean> {
  const resolvedBase = path.resolve(worktreeBasePath);
  const resolvedParent = path.dirname(path.resolve(worktreePath));
  const relative = path.relative(resolvedBase, resolvedParent);

  // Empty relative path = parent IS the base; ".." or absolute = outside it;
  // a separator means it is nested deeper than the managed <base>/<name>
  // layout. Case-insensitive filesystems surface case mismatches as ".."
  // paths, so this check fails closed.
  if (
    !relative ||
    relative.startsWith("..") ||
    path.isAbsolute(relative) ||
    relative.includes(path.sep)
  ) {
    return false;
  }

  try {
    const entries = await fsp.readdir(resolvedParent);
    if (entries.length > 0) return false;
    await fsp.rmdir(resolvedParent);
    return true;
  } catch {
    return false;
  }
}
