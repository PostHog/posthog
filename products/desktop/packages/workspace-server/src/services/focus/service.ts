import fs from "node:fs/promises";
import path from "node:path";
import * as watcher from "@parcel/watcher";
import {
  getHeadSha,
  branchExists as gitBranchExists,
  getCurrentBranch as gitGetCurrentBranch,
  hasChanges,
} from "@posthog/git/queries";
import { SwitchBranchSaga } from "@posthog/git/sagas/branch";
import { CleanWorkingTreeSaga } from "@posthog/git/sagas/clean";
import { DetachHeadSaga, ReattachBranchSaga } from "@posthog/git/sagas/head";
import {
  StashApplySaga,
  StashPopSaga,
  StashPushSaga,
} from "@posthog/git/sagas/stash";
import { TypedEventEmitter } from "@posthog/shared";
import { injectable } from "inversify";
import type {
  FocusBranchRenamedEvent,
  FocusForeignBranchCheckoutEvent,
  FocusResult,
  FocusSession,
  StashResult,
} from "./schemas";

const FocusServiceEvent = {
  BranchRenamed: "branchRenamed",
  ForeignBranchCheckout: "foreignBranchCheckout",
} as const;

type FocusServiceEvents = {
  [FocusServiceEvent.BranchRenamed]: FocusBranchRenamedEvent;
  [FocusServiceEvent.ForeignBranchCheckout]: FocusForeignBranchCheckoutEvent;
};

@injectable()
export class FocusService extends TypedEventEmitter<FocusServiceEvents> {
  private watchedMainRepo: string | null = null;
  private mainRepoSubscription: { unsubscribe(): Promise<unknown> } | null =
    null;
  private sessions = new Map<string, FocusSession>();

  async startWatchingMainRepo(mainRepoPath: string): Promise<void> {
    if (this.watchedMainRepo === mainRepoPath && this.mainRepoSubscription) {
      return;
    }

    await this.stopWatchingMainRepo();

    const gitDir = path.join(mainRepoPath, ".git");
    const subscription = await watcher.subscribe(gitDir, (error, events) => {
      if (error) {
        return;
      }

      const isRelevant = events.some(
        (event) =>
          event.path.endsWith("/HEAD") || event.path.includes("/refs/heads/"),
      );

      if (isRelevant) {
        void this.checkForBranchRename(mainRepoPath);
      }
    });

    this.watchedMainRepo = mainRepoPath;
    this.mainRepoSubscription = subscription;
  }

  async stopWatchingMainRepo(): Promise<void> {
    if (!this.mainRepoSubscription) {
      return;
    }

    await this.mainRepoSubscription.unsubscribe();
    this.mainRepoSubscription = null;
    this.watchedMainRepo = null;
  }

  getSession(mainRepoPath: string): FocusSession | null {
    return this.sessions.get(mainRepoPath) ?? null;
  }

  saveSession(session: FocusSession): void {
    this.sessions.set(session.mainRepoPath, session);
  }

  deleteSession(mainRepoPath: string): void {
    this.sessions.delete(mainRepoPath);
  }

  isFocusActive(mainRepoPath: string): boolean {
    return this.sessions.has(mainRepoPath);
  }

  branchRenamedEvents(
    signal?: AbortSignal,
  ): AsyncIterable<FocusBranchRenamedEvent> {
    return this.toIterable(FocusServiceEvent.BranchRenamed, { signal });
  }

  foreignBranchCheckoutEvents(
    signal?: AbortSignal,
  ): AsyncIterable<FocusForeignBranchCheckoutEvent> {
    return this.toIterable(FocusServiceEvent.ForeignBranchCheckout, {
      signal,
    });
  }

  async getCommitSha(repoPath: string): Promise<string> {
    return getHeadSha(repoPath);
  }

  async findWorktreeByBranch(
    mainRepoPath: string,
    branch: string,
  ): Promise<string | null> {
    const worktreesDir = path.join(mainRepoPath, ".git", "worktrees");
    const branchSuffix = branch.split("/").pop() ?? branch;

    let entries: string[];
    try {
      entries = await fs.readdir(worktreesDir);
    } catch {
      return null;
    }

    for (const name of entries) {
      if (name !== branchSuffix) continue;

      const worktreeDir = path.join(worktreesDir, name);
      const gitdirPath = path.join(worktreeDir, "gitdir");
      const headPath = path.join(worktreeDir, "HEAD");

      try {
        const [gitdirContent, headContent] = await Promise.all([
          fs.readFile(gitdirPath, "utf-8"),
          fs.readFile(headPath, "utf-8"),
        ]);

        const isDetached = !headContent.trim().startsWith("ref:");
        if (!isDetached) continue;

        return path.dirname(gitdirContent.trim());
      } catch {}
    }

    return null;
  }

  async cleanWorkingTree(repoPath: string): Promise<void> {
    const saga = new CleanWorkingTreeSaga();
    const result = await saga.run({ baseDir: repoPath });
    if (!result.success) {
      throw new Error(`Failed to clean working tree: ${result.error}`);
    }
  }

  async detachWorktree(worktreePath: string): Promise<FocusResult> {
    const saga = new DetachHeadSaga();
    const result = await saga.run({ baseDir: worktreePath });
    if (!result.success) {
      return {
        success: false,
        error: `Failed to detach worktree: ${result.error}`,
      };
    }
    return { success: true };
  }

  async reattachWorktree(
    worktreePath: string,
    branchName: string,
  ): Promise<FocusResult> {
    const saga = new ReattachBranchSaga();
    const result = await saga.run({ baseDir: worktreePath, branchName });
    if (!result.success) {
      return {
        success: false,
        error: `Failed to reattach worktree: ${result.error}`,
      };
    }
    return { success: true };
  }

  async isDirty(repoPath: string): Promise<boolean> {
    return hasChanges(repoPath);
  }

  async stash(repoPath: string, message: string): Promise<StashResult> {
    const saga = new StashPushSaga();
    const result = await saga.run({ baseDir: repoPath, message });
    if (!result.success) {
      return { success: false, error: `Failed to stash: ${result.error}` };
    }
    if (result.data.stashSha) {
      return { success: true, stashRef: result.data.stashSha };
    }
    return { success: true };
  }

  async stashApply(repoPath: string, stashRef: string): Promise<FocusResult> {
    const saga = new StashApplySaga();
    const result = await saga.run({ baseDir: repoPath, stashSha: stashRef });
    if (!result.success) {
      return {
        success: false,
        error: `Failed to apply stash: ${result.error}`,
      };
    }
    return { success: true };
  }

  async stashPop(repoPath: string): Promise<FocusResult> {
    const saga = new StashPopSaga();
    const result = await saga.run({ baseDir: repoPath });
    if (!result.success) {
      return { success: false, error: `Failed to pop stash: ${result.error}` };
    }
    return { success: true };
  }

  async checkout(repoPath: string, branch: string): Promise<FocusResult> {
    const saga = new SwitchBranchSaga();
    const result = await saga.run({ baseDir: repoPath, branchName: branch });
    if (!result.success) {
      return {
        success: false,
        error: `Failed to checkout ${branch}: ${result.error}`,
      };
    }
    return { success: true };
  }

  private async checkForBranchRename(mainRepoPath: string): Promise<void> {
    const session = this.getSession(mainRepoPath);
    if (!session) return;

    const currentBranch = await this.getCurrentBranch(mainRepoPath);
    if (!currentBranch || currentBranch === session.branch) {
      return;
    }

    const oldBranchExists = await gitBranchExists(mainRepoPath, session.branch);
    if (!oldBranchExists) {
      const oldBranch = session.branch;
      session.branch = currentBranch;
      session.commitSha = await this.getCommitSha(mainRepoPath);
      this.saveSession(session);

      this.emit(FocusServiceEvent.BranchRenamed, {
        mainRepoPath,
        worktreePath: session.worktreePath,
        oldBranch,
        newBranch: currentBranch,
      });
      return;
    }

    this.emit(FocusServiceEvent.ForeignBranchCheckout, {
      mainRepoPath,
      worktreePath: session.worktreePath,
      focusedBranch: session.branch,
      foreignBranch: currentBranch,
    });
  }

  private async getCurrentBranch(repoPath: string): Promise<string | null> {
    return (await gitGetCurrentBranch(repoPath)) ?? null;
  }
}
