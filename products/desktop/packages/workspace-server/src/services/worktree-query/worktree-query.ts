import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { createGitClient } from "@posthog/git/client";
import { listWorktrees } from "@posthog/git/queries";
import { WorktreeManager } from "@posthog/git/worktree";

const execFileAsync = promisify(execFile);

/** Current branch via `git rev-parse --abbrev-ref HEAD`; "" on error/detached. */
export async function getCurrentBranchName(
  worktreePath: string,
): Promise<string> {
  try {
    const git = createGitClient(worktreePath);
    return (await git.revparse(["--abbrev-ref", "HEAD"])).trim();
  } catch {
    return "";
  }
}

/** The local worktree path for a repo, if one currently exists on disk. */
export async function resolveLocalWorktreePath(
  mainRepoPath: string,
  worktreeBasePath: string,
): Promise<string | null> {
  try {
    const manager = new WorktreeManager({ mainRepoPath, worktreeBasePath });
    const localPath = manager.getLocalWorktreePath();
    return (await manager.localWorktreeExists()) ? localPath : null;
  } catch {
    return null;
  }
}

/** Delete a git worktree at the given path (host op via WorktreeManager). */
export async function deleteWorktree(
  mainRepoPath: string,
  worktreeBasePath: string,
  worktreePath: string,
): Promise<void> {
  const manager = new WorktreeManager({ mainRepoPath, worktreeBasePath });
  await manager.deleteWorktree(worktreePath);
}

export interface RawTwigWorktree {
  worktreePath: string;
  head: string;
  branch: string | null;
}

/**
 * Git worktrees that live under the twig worktree base path (excludes the main
 * repo). Pure git query; taskId enrichment is the caller's concern.
 */
export async function listTwigWorktrees(
  mainRepoPath: string,
  worktreeBasePath: string,
): Promise<RawTwigWorktree[]> {
  const rawWorktrees = await listWorktrees(mainRepoPath);
  return rawWorktrees
    .filter((wt) => {
      const isMainRepo = path.resolve(wt.path) === path.resolve(mainRepoPath);
      const isUnderTwig = path
        .resolve(wt.path)
        .startsWith(path.resolve(worktreeBasePath));
      return !isMainRepo && isUnderTwig;
    })
    .map((wt) => ({
      worktreePath: wt.path,
      head: wt.head,
      branch: wt.branch,
    }));
}

/**
 * Every linked git worktree for the repo, in any location (excludes the main
 * repo). Unlike `listTwigWorktrees`, this is not limited to the managed base
 * path, so it surfaces worktrees the user created by hand elsewhere. Pure git
 * query; taskId enrichment is the caller's concern.
 */
export async function listLinkedWorktrees(
  mainRepoPath: string,
): Promise<RawTwigWorktree[]> {
  const rawWorktrees = await listWorktrees(mainRepoPath);
  return rawWorktrees
    .filter((wt) => path.resolve(wt.path) !== path.resolve(mainRepoPath))
    .map((wt) => ({
      worktreePath: wt.path,
      head: wt.head,
      branch: wt.branch,
    }));
}

async function hasExcludeFileEntries(
  mainRepoPath: string,
  fileName: string,
): Promise<boolean> {
  try {
    const contents = await readFile(path.join(mainRepoPath, fileName), "utf8");
    return contents.split("\n").some((line) => {
      const trimmed = line.trim();
      return trimmed.length > 0 && !trimmed.startsWith("#");
    });
  } catch {
    return false;
  }
}

/** Disk size of a worktree via `du -s` (blocks * 512). Returns 0 on failure. */
export async function getWorktreeSize(
  worktreePath: string,
): Promise<{ sizeBytes: number }> {
  try {
    const { stdout } = await execFileAsync("du", ["-s", worktreePath]);
    const [sizeStr] = stdout.trim().split("\t");
    const sizeBytes = sizeStr ? Number.parseInt(sizeStr, 10) * 512 : 0;
    return { sizeBytes };
  } catch {
    return { sizeBytes: 0 };
  }
}

/** Whether the repo declares .worktreelink / .worktreeinclude exclude entries. */
export async function getWorktreeFileUsage(
  mainRepoPath: string,
): Promise<{ usesWorktreeLink: boolean; usesWorktreeInclude: boolean }> {
  const [usesWorktreeLink, usesWorktreeInclude] = await Promise.all([
    hasExcludeFileEntries(mainRepoPath, ".worktreelink"),
    hasExcludeFileEntries(mainRepoPath, ".worktreeinclude"),
  ]);
  return { usesWorktreeLink, usesWorktreeInclude };
}
