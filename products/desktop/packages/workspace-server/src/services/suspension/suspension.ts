import path from "node:path";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { createGitClient } from "@posthog/git/client";
import { deleteCheckpoint } from "@posthog/git/sagas/checkpoint";
import { forceRemove } from "@posthog/git/utils";
import { WorktreeManager } from "@posthog/git/worktree";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  ARCHIVE_REPOSITORY,
  REPOSITORY_REPOSITORY,
  SUSPENSION_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "../../db/identifiers";
import type { IArchiveRepository } from "../../db/repositories/archive-repository";
import type { IRepositoryRepository } from "../../db/repositories/repository-repository";
import type {
  SuspensionReason,
  SuspensionRepository,
} from "../../db/repositories/suspension-repository";
import type {
  IWorkspaceRepository,
  Workspace,
} from "../../db/repositories/workspace-repository";
import type { IWorktreeRepository } from "../../db/repositories/worktree-repository";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import {
  captureWorktreeCheckpoint,
  restoreWorktreeFromCheckpoint,
} from "../worktree-checkpoint/worktree-checkpoint";
import { deriveWorktreePath as deriveWorktreePathFromBase } from "../worktree-path/worktree-path";
import { getCurrentBranchName } from "../worktree-query/worktree-query";
import {
  SUSPENSION_FILE_WATCHER,
  SUSPENSION_SESSION_CANCELLER,
} from "./identifiers";
import type { SessionCanceller, SuspensionFileWatcher } from "./ports";
import type { SuspendedTask } from "./schemas";

type RollbackFn = () => Promise<void>;
type StepFn = (
  execute: () => Promise<void>,
  rollback?: RollbackFn,
) => Promise<void>;

export const SuspensionServiceEvent = {
  Suspended: "suspended",
  Restored: "restored",
} as const;

export interface SuspensionServiceEvents {
  [SuspensionServiceEvent.Suspended]: { taskId: string; reason: string };
  [SuspensionServiceEvent.Restored]: { taskId: string };
}

@injectable()
export class SuspensionService extends TypedEventEmitter<SuspensionServiceEvents> {
  private inactivityTimerId: ReturnType<typeof setInterval> | null = null;
  private suspendSweep: Promise<void> = Promise.resolve();
  private readonly log: ScopedLogger;

  constructor(
    @inject(SUSPENSION_SESSION_CANCELLER)
    private readonly sessionCanceller: SessionCanceller,
    @inject(PROCESS_TRACKING_SERVICE)
    private readonly processTracking: ProcessTrackingService,
    @inject(SUSPENSION_FILE_WATCHER)
    private readonly fileWatcher: SuspensionFileWatcher,
    @inject(REPOSITORY_REPOSITORY)
    private readonly repositoryRepo: IRepositoryRepository,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: IWorkspaceRepository,
    @inject(WORKTREE_REPOSITORY)
    private readonly worktreeRepo: IWorktreeRepository,
    @inject(SUSPENSION_REPOSITORY)
    private readonly suspensionRepo: SuspensionRepository,
    @inject(ARCHIVE_REPOSITORY)
    private readonly archiveRepo: IArchiveRepository,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly workspaceSettings: IWorkspaceSettings,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    super();
    this.log = logger.scope("suspension");
  }

  async suspendTask(
    taskId: string,
    reason: SuspensionReason,
  ): Promise<SuspendedTask> {
    this.log.info(`Suspending task ${taskId} (reason: ${reason})`);
    const result = await this.withRollback((step) =>
      this.executeSuspend(taskId, reason, step),
    );
    this.emit(SuspensionServiceEvent.Suspended, { taskId, reason });
    return result;
  }

  async restoreTask(
    taskId: string,
    recreateBranch?: boolean,
  ): Promise<{ taskId: string; worktreeName: string | null }> {
    this.log.info(
      `Restoring suspended task ${taskId}${recreateBranch ? " (recreate branch)" : ""}`,
    );
    const result = await this.withRollback((step) =>
      this.executeRestore(taskId, recreateBranch, step),
    );
    this.emit(SuspensionServiceEvent.Restored, { taskId });
    return result;
  }

  getSuspendedTasks(): SuspendedTask[] {
    return this.suspensionRepo.findAll().map((suspension) => {
      const workspace = this.workspaceRepo.findById(
        suspension.workspaceId,
      ) as Workspace;
      const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
      return {
        taskId: workspace.taskId,
        suspendedAt: suspension.suspendedAt,
        reason: suspension.reason as SuspendedTask["reason"],
        folderId: workspace.repositoryId ?? "",
        mode: workspace.mode as SuspendedTask["mode"],
        worktreeName: worktree?.name ?? null,
        branchName: suspension.branchName,
        checkpointId: suspension.checkpointId,
      };
    });
  }

  getSuspendedTaskIds(): string[] {
    return this.getSuspendedTasks().map((t) => t.taskId);
  }

  isSuspended(taskId: string): boolean {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) return false;
    return this.suspensionRepo.findByWorkspaceId(workspace.id) !== null;
  }

  /**
   * Suspends the least-recently-active worktree tasks until the active count
   * is back at the cap. Runs after a workspace is created (not before), so the
   * expensive checkpoint-and-delete never blocks creating a new session.
   *
   * Sweeps are serialized: it is called fire-and-forget from every worktree
   * creation, and two concurrent sweeps would each read the same `active` list
   * and pick the same oldest task, double-deleting one worktree. Chaining makes
   * each sweep re-read `active` after the previous one's suspensions commit. The
   * `.catch` keeps a failed sweep from wedging the chain for later callers.
   */
  suspendLeastRecentIfOverLimit(): Promise<void> {
    this.suspendSweep = this.suspendSweep
      .catch(() => {})
      .then(() => this.runSuspendSweep());
    return this.suspendSweep;
  }

  private async runSuspendSweep(): Promise<void> {
    if (!this.workspaceSettings.getAutoSuspendEnabled()) return;
    const maxActive = this.workspaceSettings.getMaxActiveWorktrees();
    const active = this.getActiveWorktreeWorkspaces();
    const excess = active.length - maxActive;
    if (excess <= 0) return;

    const oldestFirst = active.sort((a, b) => {
      const aTime = a.lastActivityAt ?? a.createdAt ?? "";
      const bTime = b.lastActivityAt ?? b.createdAt ?? "";
      return aTime.localeCompare(bTime);
    });

    this.log.info(
      `Auto-suspending ${excess} task(s) over the worktree cap (max: ${maxActive}, active: ${active.length})`,
    );
    for (const workspace of oldestFirst.slice(0, excess)) {
      await this.autoSuspend(workspace.taskId, "max_worktrees");
    }
  }

  async suspendInactiveWorktrees(): Promise<void> {
    if (!this.workspaceSettings.getAutoSuspendEnabled()) return;
    const thresholdDays = this.workspaceSettings.getAutoSuspendAfterDays();

    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - thresholdDays);
    const cutoffStr = cutoff.toISOString();

    const candidates = this.getActiveWorktreeWorkspaces().filter((ws) => {
      return (ws.lastActivityAt ?? ws.createdAt ?? "") < cutoffStr;
    });

    for (const ws of candidates) {
      this.log.info(
        `Auto-suspending inactive task ${ws.taskId} (last activity: ${ws.lastActivityAt ?? ws.createdAt})`,
      );
      await this.autoSuspend(ws.taskId, "inactivity");
    }
  }

  startInactivityChecker(): void {
    if (this.inactivityTimerId) return;
    const ONE_HOUR_MS = 60 * 60 * 1000;
    this.inactivityTimerId = setInterval(() => {
      this.suspendInactiveWorktrees().catch((error) => {
        this.log.error("Inactivity checker failed:", error);
      });
    }, ONE_HOUR_MS);
  }

  stopInactivityChecker(): void {
    if (!this.inactivityTimerId) return;
    clearInterval(this.inactivityTimerId);
    this.inactivityTimerId = null;
  }

  getSettings() {
    return {
      autoSuspendEnabled: this.workspaceSettings.getAutoSuspendEnabled(),
      maxActiveWorktrees: this.workspaceSettings.getMaxActiveWorktrees(),
      autoSuspendAfterDays: this.workspaceSettings.getAutoSuspendAfterDays(),
    };
  }

  updateSettings(settings: {
    autoSuspendEnabled?: boolean;
    maxActiveWorktrees?: number;
    autoSuspendAfterDays?: number;
  }) {
    if (settings.autoSuspendEnabled !== undefined)
      this.workspaceSettings.setAutoSuspendEnabled(settings.autoSuspendEnabled);
    if (settings.maxActiveWorktrees !== undefined)
      this.workspaceSettings.setMaxActiveWorktrees(settings.maxActiveWorktrees);
    if (settings.autoSuspendAfterDays !== undefined)
      this.workspaceSettings.setAutoSuspendAfterDays(
        settings.autoSuspendAfterDays,
      );
  }

  private async withRollback<T>(fn: (step: StepFn) => Promise<T>): Promise<T> {
    const rollbacks: RollbackFn[] = [];
    const step: StepFn = async (execute, rollback) => {
      await execute();
      if (rollback) rollbacks.push(rollback);
    };

    try {
      return await fn(step);
    } catch (error) {
      for (const rollback of rollbacks.reverse()) {
        try {
          await rollback();
        } catch (e) {
          this.log.error("Rollback failed:", e);
        }
      }
      throw error;
    }
  }

  private getActiveWorktreeWorkspaces(): Workspace[] {
    return this.workspaceRepo.findAll().filter((ws) => {
      if (ws.mode !== "worktree") return false;
      if (this.suspensionRepo.findByWorkspaceId(ws.id)) return false;
      if (this.archiveRepo.findByWorkspaceId(ws.id)) return false;
      return true;
    });
  }

  private async autoSuspend(
    taskId: string,
    reason: SuspensionReason,
  ): Promise<void> {
    try {
      await this.suspendTask(taskId, reason);
    } catch (error) {
      this.log.error(`Failed to auto-suspend task ${taskId}:`, error);
    }
  }

  private getWorkspaceWithRepo(taskId: string) {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) throw new Error(`Workspace not found for task ${taskId}`);

    let folderPath: string | null = null;
    if (workspace.repositoryId) {
      const repo = this.repositoryRepo.findById(workspace.repositoryId);
      if (!repo) throw new Error(`Repository not found for task ${taskId}`);
      folderPath = repo.path;
    }

    return { workspace, folderPath };
  }

  private createWorktreeManager(folderPath: string) {
    return new WorktreeManager({
      mainRepoPath: folderPath,
      worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
      logger: this.log,
    });
  }

  private async deleteWorktreeOnDisk(
    folderPath: string,
    worktreePath: string,
  ): Promise<void> {
    const manager = this.createWorktreeManager(folderPath);
    await manager.deleteWorktree(worktreePath);
    await forceRemove(path.dirname(worktreePath));
  }

  private async killTaskProcesses(
    taskId: string,
    worktreePath?: string,
  ): Promise<void> {
    await this.sessionCanceller.cancelSessionsByTaskId(taskId);
    this.processTracking.killByTaskId(taskId);
    if (worktreePath) await this.fileWatcher.stopWatching(worktreePath);
  }

  private async executeSuspend(
    taskId: string,
    reason: SuspensionReason,
    step: StepFn,
  ): Promise<SuspendedTask> {
    const { workspace, folderPath } = this.getWorkspaceWithRepo(taskId);

    if (this.suspensionRepo.findByWorkspaceId(workspace.id))
      throw new Error(`Task ${taskId} is already suspended`);
    if (this.archiveRepo.findByWorkspaceId(workspace.id))
      throw new Error(`Task ${taskId} is already archived`);

    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
    const isWorktreeMode =
      workspace.mode === "worktree" && worktree && folderPath;

    const suspendedTask: SuspendedTask = {
      taskId,
      suspendedAt: new Date().toISOString(),
      reason,
      folderId: workspace.repositoryId ?? "",
      mode: workspace.mode,
      worktreeName: worktree?.name ?? null,
      branchName: null,
      checkpointId: isWorktreeMode ? `suspension-${worktree.name}` : null,
    };

    if (isWorktreeMode) {
      const worktreePath = worktree.path;

      const branch = await this.getCurrentBranchName(worktreePath);
      if (branch && branch !== "HEAD") suspendedTask.branchName = branch;

      const checkpointId = suspendedTask.checkpointId;
      if (!checkpointId)
        throw new Error("checkpointId must be set in worktree mode");

      await step(
        async () => {
          await this.captureWorktreeCheckpoint(
            folderPath,
            worktreePath,
            checkpointId,
          );
        },
        async () => {
          const git = createGitClient(folderPath);
          await deleteCheckpoint(git, checkpointId);
        },
      );

      await step(async () => this.killTaskProcesses(taskId, worktreePath));
      await step(async () =>
        this.deleteWorktreeOnDisk(folderPath, worktreePath),
      );
    } else {
      await step(async () => this.killTaskProcesses(taskId));
    }

    await step(
      async () => {
        this.suspensionRepo.create({
          workspaceId: workspace.id,
          branchName: suspendedTask.branchName,
          checkpointId: suspendedTask.checkpointId,
          reason,
        });
      },
      async () => this.suspensionRepo.deleteByWorkspaceId(workspace.id),
    );

    return suspendedTask;
  }

  private async executeRestore(
    taskId: string,
    recreateBranch: boolean | undefined,
    step: StepFn,
  ): Promise<{ taskId: string; worktreeName: string | null }> {
    const { workspace, folderPath } = this.getWorkspaceWithRepo(taskId);

    const suspension = this.suspensionRepo.findByWorkspaceId(workspace.id);
    if (!suspension) throw new Error(`Suspended task not found: ${taskId}`);

    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
    let restoredWorktreeName: string | null = worktree?.name ?? null;

    if (
      folderPath &&
      workspace.mode === "worktree" &&
      suspension.checkpointId
    ) {
      const checkpointId = suspension.checkpointId;
      await step(
        async () => {
          restoredWorktreeName = await this.restoreWorktreeFromCheckpoint(
            folderPath,
            workspace,
            suspension.branchName,
            checkpointId,
            recreateBranch,
          );
        },
        async () => {
          if (restoredWorktreeName) {
            const worktreePath = await this.deriveWorktreePath(
              folderPath,
              restoredWorktreeName,
            );
            await this.deleteWorktreeOnDisk(folderPath, worktreePath);
          }
        },
      );

      await step(
        async () => {
          if (!restoredWorktreeName)
            throw new Error("Failed to restore worktree");
          const worktreePath = await this.deriveWorktreePath(
            folderPath,
            restoredWorktreeName,
          );
          this.worktreeRepo.create({
            workspaceId: workspace.id,
            name: restoredWorktreeName,
            path: worktreePath,
          });
        },
        async () => this.worktreeRepo.deleteByWorkspaceId(workspace.id),
      );
    }

    await step(
      async () => this.suspensionRepo.deleteByWorkspaceId(workspace.id),
      async () => {
        this.suspensionRepo.create({
          workspaceId: workspace.id,
          branchName: suspension.branchName,
          checkpointId: suspension.checkpointId,
          reason: suspension.reason as SuspensionReason,
        });
      },
    );

    return { taskId, worktreeName: restoredWorktreeName };
  }

  private getCurrentBranchName(worktreePath: string): Promise<string> {
    return getCurrentBranchName(worktreePath);
  }

  private captureWorktreeCheckpoint(
    folderPath: string,
    worktreePath: string,
    checkpointId: string,
  ): Promise<void> {
    return captureWorktreeCheckpoint(folderPath, worktreePath, checkpointId);
  }

  private async restoreWorktreeFromCheckpoint(
    folderPath: string,
    workspace: Workspace,
    branchName: string | null,
    checkpointId: string,
    recreateBranch?: boolean,
  ): Promise<string> {
    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);

    const newWorktree = await restoreWorktreeFromCheckpoint({
      mainRepoPath: folderPath,
      worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
      preferredName: worktree?.name ?? undefined,
      branchName,
      checkpointId,
      recreateBranch,
      logger: this.log,
    });

    if (worktree) this.worktreeRepo.deleteByWorkspaceId(workspace.id);
    return newWorktree.worktreeName;
  }

  private deriveWorktreePath(folderPath: string, worktreeName: string): string {
    return deriveWorktreePathFromBase(
      this.workspaceSettings.getWorktreeLocation(),
      folderPath,
      worktreeName,
    );
  }
}
