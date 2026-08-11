import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

/** True if the directory contains any entry other than `.git`. */
export async function hasAnyFiles(repoPath: string): Promise<boolean> {
  try {
    const entries = await readdir(repoPath);
    return entries.some((entry) => entry !== ".git");
  } catch {
    return false;
  }
}

/**
 * Current branch for a repo or worktree, read directly from its Git HEAD file
 * (no subprocess). Returns null for detached HEAD or if the path is not a repo.
 */
export async function getBranchFromPath(
  repoPath: string,
): Promise<string | null> {
  try {
    const gitPath = path.join(repoPath, ".git");
    const gitStat = await stat(gitPath);

    let headPath: string;
    if (gitStat.isDirectory()) {
      headPath = path.join(gitPath, "HEAD");
    } else {
      const gitContent = await readFile(gitPath, "utf-8");
      const gitdirMatch = gitContent.match(/gitdir:\s*(.+)/);
      if (!gitdirMatch) return null;
      headPath = path.join(path.resolve(gitdirMatch[1].trim()), "HEAD");
    }

    const headContent = await readFile(headPath, "utf-8");
    const branchMatch = headContent.match(/ref: refs\/heads\/(.+)/);
    return branchMatch ? branchMatch[1].trim() : null;
  } catch {
    return null;
  }
}
