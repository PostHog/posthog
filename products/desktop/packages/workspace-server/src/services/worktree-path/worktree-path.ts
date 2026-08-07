import * as fs from "node:fs";
import path from "node:path";

/**
 * Resolves a worktree's on-disk path by probing both folder layouts: nested
 * (`<base>/<name>/<repo>`, the "codename" naming scheme) and grouped
 * (`<base>/<repo>/<name>`, the "descriptive" scheme and pre-restructure
 * worktrees). Checks disk because the name alone cannot identify the layout;
 * when neither exists, falls back to the nested shape. Last-resort recovery
 * only: a stored worktree path is authoritative wherever one exists.
 */
export function deriveWorktreePath(
  worktreeBasePath: string,
  folderPath: string,
  worktreeName: string,
): string {
  const repoName = path.basename(folderPath);

  const nestedPath = path.join(worktreeBasePath, worktreeName, repoName);
  const groupedPath = path.join(worktreeBasePath, repoName, worktreeName);

  if (fs.existsSync(nestedPath)) return nestedPath;
  if (fs.existsSync(groupedPath)) return groupedPath;
  return nestedPath;
}
