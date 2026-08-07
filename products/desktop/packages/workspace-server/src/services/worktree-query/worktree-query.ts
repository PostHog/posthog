import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { createGitClient } from "@posthog/git/client";
import { listWorktrees } from "@posthog/git/queries";
import { forceRemove } from "@posthog/git/utils";
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

/**
 * Whether the parent directory of a worktree is a dedicated per-worktree
 * container that may be removed along with it. True for the nested layout
 * (`<base>/<name>/<repo>`, where the parent exists only for this worktree);
 * false for the grouped layout (`<base>/<repo>/<name>`, where the parent is
 * shared by every worktree of the repo and removing it would delete siblings).
 *
 * Distinguishes the layouts by whether the leaf folder is the repo name. This
 * is sound only because WorktreeManager reserves the repo name as a worktree
 * name (see RESERVED_WORKTREE_NAMES and the repo-name guard), so a grouped
 * worktree can never have the repo name as its leaf.
 */
export function isDedicatedWorktreeContainer(
  worktreePath: string,
  mainRepoPath: string,
): boolean {
  return path.basename(worktreePath) === path.basename(mainRepoPath);
}

/**
 * Remove a deleted worktree's dedicated container directory; a shared
 * (grouped-layout) parent holding sibling worktrees is left in place.
 */
export async function removeWorktreeContainer(
  worktreePath: string,
  mainRepoPath: string,
): Promise<void> {
  if (!isDedicatedWorktreeContainer(worktreePath, mainRepoPath)) return;
  await forceRemove(path.dirname(worktreePath));
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
