import path from "node:path";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { createGitClient } from "@posthog/git/client";
import { isGitRepository } from "@posthog/git/queries";
import { deleteCheckpoint } from "@posthog/git/sagas/checkpoint";
import { forceRemove } from "@posthog/git/utils";
import { WorktreeManager } from "@posthog/git/worktree";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import { inject, injectable } from "inversify";
import {
  ARCHIVE_REPOSITORY,
  REPOSITORY_REPOSITORY,
  SUSPENSION_REPOSITORY,
  TASK_METADATA_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "../../db/identifiers";
import type {
  Archive,
  ArchiveRepository,
} from "../../db/repositories/archive-repository";
import type { RepositoryRepository } from "../../db/repositories/repository-repository";
import type {
  SuspensionReason,
  SuspensionRepository,
} from "../../db/repositories/suspension-repository";
import type {
  ITaskMetadataRepository,
  TaskMetadataRow,
} from "../../db/repositories/task-metadata-repository";
import type {
  Workspace,
  WorkspaceRepository,
} from "../../db/repositories/workspace-repository";
import type { WorktreeRepository } from "../../db/repositories/worktree-repository";
import {
  IMPORTED_SESSION_CLEANER,
  type ImportedSessionCleaner,
} from "../claude-cli-sessions/identifiers";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import {
  captureWorktreeCheckpoint,
  restoreWorktreeFromCheckpoint,
} from "../worktree-checkpoint/worktree-checkpoint";
import { deriveWorktreePath as deriveWorktreePathFromBase } from "../worktree-path/worktree-path";
import { getCurrentBranchName } from "../worktree-query/worktree-query";
import { recoverArchiveDetailsFromLogs } from "./archive-recovery";
import { ARCHIVE_FILE_WATCHER, ARCHIVE_SESSION_CANCELLER } from "./identifiers";
import type { ArchiveFileWatcher, SessionCanceller } from "./ports";
import type { ArchivedTask, ArchiveTaskInput } from "./schemas";

type RollbackFn = () => Promise<void>;

@injectable()
export class ArchiveService {
  constructor(
    @inject(ARCHIVE_SESSION_CANCELLER)
    private readonly sessionCanceller: SessionCanceller,
    @inject(PROCESS_TRACKING_SERVICE)
    private readonly processTracking: ProcessTrackingService,
    @inject(ARCHIVE_FILE_WATCHER)
    private readonly fileWatcher: ArchiveFileWatcher,
    @inject(REPOSITORY_REPOSITORY)
    private readonly repositoryRepo: RepositoryRepository,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: WorkspaceRepository,
    @inject(WORKTREE_REPOSITORY)
    private readonly worktreeRepo: WorktreeRepository,
    @inject(ARCHIVE_REPOSITORY)
    private readonly archiveRepo: ArchiveRepository,
    @inject(SUSPENSION_REPOSITORY)
    private readonly suspensionRepo: SuspensionRepository,
    @inject(TASK_METADATA_REPOSITORY)
    private readonly taskMetadataRepo: ITaskMetadataRepository,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly workspaceSettings: IWorkspaceSettings,
    @inject(IMPORTED_SESSION_CLEANER)
    private readonly importedSessionCleaner: ImportedSessionCleaner,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("archive");
  }

  private readonly log: ScopedLogger;
  private recoveryStarted = false;

  async archiveTask(input: ArchiveTaskInput): Promise<ArchivedTask> {
    this.log.info(`Archiving task ${input.taskId}`);

    const rollbacks: RollbackFn[] = [];
    const runWithRollback = async (
      execute: () => Promise<void>,
      rollback: RollbackFn,
    ) => {
      await execute();
      rollbacks.push(rollback);
    };

    try {
      const result = await this.executeArchive(input, runWithRollback);
      if (!input.title) {
        this.recoveryStarted = false;
      }
      this.log.info(`Task ${input.taskId} archived successfully`);
      return result;
    } catch (error) {
      for (const rollback of rollbacks.reverse()) {
        try {
          await rollback();
        } catch (rollbackError) {
          this.log.error("Rollback failed:", rollbackError);
        }
      }
      throw error;
    }
  }

  private async executeArchive(
    input: ArchiveTaskInput,
    step: (execute: () => Promise<void>, rollback: RollbackFn) => Promise<void>,
  ): Promise<ArchivedTask> {
    const { taskId } = input;

    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) {
      // Rowless channel task: no workspace/worktree to tear down. Record the
      // archived state in task_metadata so it actually persists — otherwise
      // `getArchivedTaskIds` never reports it and the row reappears on refetch.
      const existing = this.taskMetadataRepo.findByTaskId(taskId);
      if (existing?.archivedAt) {
        throw new Error(`Task ${taskId} is already archived`);
      }
      const archivedAt = new Date().toISOString();
      await step(
        async () => {
          this.taskMetadataRepo.upsert(taskId, {
            archivedAt,
            archivedTitle: input.title ?? null,
            archivedTaskCreatedAt: input.taskCreatedAt ?? null,
            archivedRepository: input.repository ?? null,
          });
        },
        async () => {
          this.taskMetadataRepo.upsert(taskId, { archivedAt: null });
        },
      );
      return {
        taskId,
        archivedAt,
        folderId: "",
        mode: "cloud",
        worktreeName: null,
        branchName: null,
        checkpointId: null,
        title: input.title ?? null,
        taskCreatedAt: input.taskCreatedAt ?? null,
        repository: input.repository ?? null,
      };
    }

    const existingArchive = this.archiveRepo.findByWorkspaceId(workspace.id);
    if (existingArchive) {
      throw new Error(`Task ${taskId} is already archived`);
    }

    const suspension = this.suspensionRepo.findByWorkspaceId(workspace.id);
    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);

    if (suspension) {
      const archivedTask: ArchivedTask = {
        taskId,
        archivedAt: new Date().toISOString(),
        folderId: workspace.repositoryId ?? "",
        mode: workspace.mode,
        worktreeName: worktree?.name ?? null,
        branchName: suspension.branchName,
        checkpointId: suspension.checkpointId,
      };

      await step(
        async () => {
          this.archiveRepo.create({
            workspaceId: workspace.id,
            branchName: archivedTask.branchName,
            checkpointId: archivedTask.checkpointId,
            title: input.title ?? null,
            taskCreatedAt: input.taskCreatedAt ?? null,
            repository: input.repository ?? null,
          });
        },
        async () => {
          this.archiveRepo.deleteByWorkspaceId(workspace.id);
        },
      );

      await step(
        async () => {
          this.suspensionRepo.deleteByWorkspaceId(workspace.id);
        },
        async () => {
          this.suspensionRepo.create({
            workspaceId: workspace.id,
            branchName: suspension.branchName,
            checkpointId: suspension.checkpointId,
            reason: suspension.reason as SuspensionReason,
          });
        },
      );

      return archivedTask;
    }

    const archivedTask: ArchivedTask = {
      taskId,
      archivedAt: new Date().toISOString(),
      folderId: workspace.repositoryId ?? "",
      mode: workspace.mode,
      worktreeName: worktree?.name ?? null,
      branchName: null,
      checkpointId:
        workspace.mode === "worktree" && worktree
          ? `worktree-${worktree.name}`
          : null,
    };

    if (workspace.repositoryId) {
      const repo = this.repositoryRepo.findById(workspace.repositoryId);
      if (!repo) {
        throw new Error(`Repository not found for task ${taskId}`);
      }
      const folderPath = repo.path;

      if (workspace.mode === "worktree" && worktree) {
        const worktreePath = worktree.path;
        const worktreeIsValid = await isGitRepository(worktreePath).catch(
          (error) => {
            this.log.warn(
              `Failed to check worktree at ${worktreePath}; treating as invalid`,
              { error },
            );
            return false;
          },
        );

        if (!worktreeIsValid) {
          this.log.warn(
            `Worktree at ${worktreePath} is missing or not a git repository; skipping checkpoint capture`,
          );
          archivedTask.checkpointId = null;
        } else {
          const actualBranch = await this.getCurrentBranchName(worktreePath);
          if (actualBranch && actualBranch !== "HEAD") {
            archivedTask.branchName = actualBranch;
          }

          const checkpointId = archivedTask.checkpointId;
          try {
            if (!checkpointId) {
              throw new Error("checkpointId must be set for worktree mode");
            }
            await step(
              () =>
                this.captureWorktreeCheckpoint(
                  folderPath,
                  worktreePath,
                  checkpointId,
                ),
              async () => {
                const git = createGitClient(folderPath);
                await deleteCheckpoint(git, checkpointId);
              },
            );
          } catch (error) {
            this.log.warn(
              `Failed to capture checkpoint for ${worktreePath}; archiving without a restore point`,
              { error },
            );
            archivedTask.checkpointId = null;
          }
        }

        await step(
          async () => {
            await this.sessionCanceller.cancelSessionsByTaskId(taskId);
            this.processTracking.killByTaskId(taskId);
            await this.fileWatcher.stopWatching(worktreePath);
          },
          async () => {},
        );

        await step(
          async () => {
            try {
              const manager = new WorktreeManager({
                mainRepoPath: folderPath,
                worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
                logger: this.log,
              });
              await manager.deleteWorktree(worktreePath);
              const parentDir = path.dirname(worktreePath);
              await forceRemove(parentDir);
            } catch (error) {
              this.log.warn(
                `Failed to remove worktree at ${worktreePath}; archiving anyway (on-disk worktree may need manual cleanup)`,
                { error },
              );
              // The worktree is still registered under its original name, so a
              // later unarchive can't re-add it from the checkpoint (git rejects
              // the duplicate name/path), leaving the task un-restorable. Drop
              // the restore point — and its now-orphaned checkpoint ref — so the
              // archive record stays internally consistent, matching how a
              // failed capture above already sets checkpointId to null.
              const orphanedCheckpointId = archivedTask.checkpointId;
              if (orphanedCheckpointId) {
                archivedTask.checkpointId = null;
                try {
                  const git = createGitClient(folderPath);
                  await deleteCheckpoint(git, orphanedCheckpointId);
                } catch (cleanupError) {
                  this.log.warn(
                    `Failed to delete orphaned checkpoint ${orphanedCheckpointId}`,
                    { error: cleanupError },
                  );
                }
              }
            }
          },
          async () => {},
        );
      }
    }

    if (workspace.mode !== "worktree") {
      await step(
        async () => {
          await this.sessionCanceller.cancelSessionsByTaskId(taskId);
          this.processTracking.killByTaskId(taskId);
        },
        async () => {},
      );
    }

    await step(
      async () => {
        this.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: archivedTask.branchName,
          checkpointId: archivedTask.checkpointId,
          title: input.title ?? null,
          taskCreatedAt: input.taskCreatedAt ?? null,
          repository: input.repository ?? null,
        });
      },
      async () => {
        this.archiveRepo.deleteByWorkspaceId(workspace.id);
      },
    );

    return archivedTask;
  }

  async unarchiveTask(
    taskId: string,
    recreateBranch?: boolean,
  ): Promise<{ taskId: string; worktreeName: string | null }> {
    this.log.info(
      `Unarchiving task ${taskId}${recreateBranch ? " (recreate branch)" : ""}`,
    );

    const rollbacks: RollbackFn[] = [];
    const runWithRollback = async (
      execute: () => Promise<void>,
      rollback: RollbackFn,
    ) => {
      await execute();
      rollbacks.push(rollback);
    };

    try {
      const result = await this.executeUnarchive(
        taskId,
        recreateBranch,
        runWithRollback,
      );
      this.log.info(`Task ${taskId} unarchived successfully`);
      return result;
    } catch (error) {
      for (const rollback of rollbacks.reverse()) {
        try {
          await rollback();
        } catch (rollbackError) {
          this.log.error("Rollback failed:", rollbackError);
        }
      }
      throw error;
    }
  }

  private async executeUnarchive(
    taskId: string,
    recreateBranch: boolean | undefined,
    step: (execute: () => Promise<void>, rollback: RollbackFn) => Promise<void>,
  ): Promise<{ taskId: string; worktreeName: string | null }> {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) {
      // Rowless channel task archived via task_metadata — just clear the flag.
      const meta = this.taskMetadataRepo.findByTaskId(taskId);
      if (!meta?.archivedAt) {
        throw new Error(`Workspace not found: ${taskId}`);
      }
      this.taskMetadataRepo.upsert(taskId, { archivedAt: null });
      return { taskId, worktreeName: null };
    }

    const archive = this.archiveRepo.findByWorkspaceId(workspace.id);
    if (!archive) {
      throw new Error(`Archived task not found: ${taskId}`);
    }

    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
    let restoredWorktreeName: string | null = worktree?.name ?? null;

    if (workspace.repositoryId) {
      const repo = this.repositoryRepo.findById(workspace.repositoryId);
      if (!repo) {
        throw new Error(`Repository not found for task ${taskId}`);
      }
      const folderPath = repo.path;

      const shouldRestoreWorktree =
        workspace.mode === "worktree" && archive.checkpointId;

      if (shouldRestoreWorktree) {
        await step(
          async () => {
            restoredWorktreeName = await this.restoreWorktreeFromCheckpoint(
              folderPath,
              workspace,
              archive,
              recreateBranch,
            );
          },
          async () => {
            if (restoredWorktreeName) {
              const manager = new WorktreeManager({
                mainRepoPath: folderPath,
                worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
                logger: this.log,
              });
              const worktreePath = await this.deriveWorktreePath(
                folderPath,
                restoredWorktreeName,
              );
              await manager.deleteWorktree(worktreePath);
              const parentDir = path.dirname(worktreePath);
              await forceRemove(parentDir);
            }
          },
        );

        await step(
          async () => {
            if (!restoredWorktreeName) {
              throw new Error("Failed to restore worktree");
            }
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
          async () => {
            this.worktreeRepo.deleteByWorkspaceId(workspace.id);
          },
        );
      }
    }

    await step(
      async () => {
        this.archiveRepo.deleteByWorkspaceId(workspace.id);
      },
      async () => {
        this.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: archive.branchName,
          checkpointId: archive.checkpointId,
          title: archive.title,
          taskCreatedAt: archive.taskCreatedAt,
          repository: archive.repository,
        });
      },
    );

    return { taskId, worktreeName: restoredWorktreeName };
  }

  getArchivedTasks(): ArchivedTask[] {
    const fromWorkspaces = this.archiveRepo.findAll().map((archive) => {
      const workspace = this.workspaceRepo.findById(
        archive.workspaceId,
      ) as Workspace;
      const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
      return this.toArchivedTask(
        workspace,
        archive,
        worktree?.name ?? null,
        worktree?.path ?? null,
      );
    });
    const rowless = this.rowlessArchived().map(
      (meta): ArchivedTask => ({
        taskId: meta.taskId,
        // `rowlessArchived` only returns rows with a non-null `archivedAt`.
        archivedAt: meta.archivedAt as string,
        folderId: "",
        mode: "cloud",
        worktreeName: null,
        branchName: null,
        checkpointId: null,
        title:
          meta.archivedTitle ?? `Unknown task (${meta.taskId.slice(0, 8)})`,
        taskCreatedAt: meta.archivedTaskCreatedAt ?? meta.createdAt,
        repository: meta.archivedRepository,
        recoveryPending: !meta.archivedTitle,
      }),
    );
    return [...fromWorkspaces, ...rowless];
  }

  async listArchivedTasks(): Promise<ArchivedTask[]> {
    if (!this.recoveryStarted) {
      this.recoveryStarted = true;
      void this.recoverArchivedTaskDetails().catch((error) => {
        this.recoveryStarted = false;
        this.log.warn("Failed to recover archived task details", { error });
      });
    }
    return this.getArchivedTasks();
  }

  private async recoverArchivedTaskDetails(): Promise<void> {
    const missing = this.archiveRepo
      .findAll()
      .filter((archive) => !archive.title)
      .map((archive) => ({
        archive,
        workspace: this.workspaceRepo.findById(archive.workspaceId),
      }))
      .filter(
        (item): item is { archive: Archive; workspace: Workspace } =>
          item.workspace !== null,
      );
    const rowlessMissing = this.rowlessArchived().filter(
      (metadata) => !metadata.archivedTitle,
    );
    const recovered = await recoverArchiveDetailsFromLogs(
      new Set([
        ...missing.map(({ workspace }) => workspace.taskId),
        ...rowlessMissing.map((metadata) => metadata.taskId),
      ]),
    );
    const byTaskId = new Map(
      recovered.map((details) => [details.taskId, details]),
    );
    for (const { archive, workspace } of missing) {
      const details = byTaskId.get(workspace.taskId);
      const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);
      const repository = workspace.repositoryId
        ? this.repositoryRepo.findById(workspace.repositoryId)
        : null;
      const recoveredTitle = details?.title;
      const title =
        recoveredTitle && !recoveredTitle.startsWith("Unknown task (")
          ? recoveredTitle
          : this.unknownTaskTitle(
              workspace.taskId,
              archive.branchName,
              worktree?.name ?? null,
            );
      this.archiveRepo.updateDetailsByWorkspaceId(archive.workspaceId, {
        title,
        taskCreatedAt: details?.taskCreatedAt ?? workspace.createdAt,
        repository: repository?.path ?? details?.repository ?? worktree?.path,
      });
    }
    for (const metadata of rowlessMissing) {
      const details = byTaskId.get(metadata.taskId);
      this.taskMetadataRepo.upsert(metadata.taskId, {
        archivedTitle:
          details?.title ?? this.unknownTaskTitle(metadata.taskId, null, null),
        archivedTaskCreatedAt: details?.taskCreatedAt ?? metadata.createdAt,
        archivedRepository: details?.repository ?? metadata.archivedRepository,
      });
    }
  }

  // Tasks archived via `task_metadata` (no `workspaces` row). A task that has a
  // workspace row is owned by the `archives` table, so it's excluded here even
  // if an `archivedAt` lingers in its metadata — otherwise it would surface
  // twice in the archived lists.
  private rowlessArchived(): TaskMetadataRow[] {
    return this.taskMetadataRepo
      .findAllArchived()
      .filter((meta) => !this.workspaceRepo.findByTaskId(meta.taskId));
  }

  getArchivedTaskIds(): string[] {
    const fromWorkspaces = this.archiveRepo
      .findAll()
      .map((archive) => {
        const workspace = this.workspaceRepo.findById(archive.workspaceId);
        return workspace?.taskId;
      })
      .filter((id): id is string => id !== undefined);
    const rowless = this.rowlessArchived().map((meta) => meta.taskId);
    return [...fromWorkspaces, ...rowless];
  }

  isArchived(taskId: string): boolean {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) {
      return this.taskMetadataRepo.findByTaskId(taskId)?.archivedAt != null;
    }
    return this.archiveRepo.findByWorkspaceId(workspace.id) !== null;
  }

  async deleteArchivedTask(taskId: string): Promise<void> {
    this.log.info(`Deleting archived task ${taskId}`);

    // Drop any imported CLI snapshot for this task. Best-effort: a cleanup
    // failure must not block deleting the archived task.
    await this.importedSessionCleaner
      .deleteImportForTask(taskId)
      .catch((error) => {
        this.log.warn("Failed to clean up imported session", { taskId, error });
      });

    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (!workspace) {
      // Rowless channel task: its archived state lives in task_metadata.
      const meta = this.taskMetadataRepo.findByTaskId(taskId);
      if (!meta?.archivedAt) {
        throw new Error(`Workspace not found: ${taskId}`);
      }
      this.taskMetadataRepo.delete(taskId);
      this.log.info(`Deleted archived task ${taskId}`);
      return;
    }

    const archive = this.archiveRepo.findByWorkspaceId(workspace.id);
    if (!archive) {
      throw new Error(`Archived task ${taskId} not found`);
    }

    if (archive.checkpointId && workspace.repositoryId) {
      const repo = this.repositoryRepo.findById(workspace.repositoryId);
      if (repo) {
        try {
          const git = createGitClient(repo.path);
          await deleteCheckpoint(git, archive.checkpointId);
        } catch (error) {
          this.log.warn(`Failed to delete checkpoint ${archive.checkpointId}`, {
            error,
          });
        }
      }
    }

    this.archiveRepo.deleteByWorkspaceId(workspace.id);
    this.workspaceRepo.deleteByTaskId(taskId);
    this.log.info(`Deleted archived task ${taskId}`);
  }

  private toArchivedTask(
    workspace: Workspace,
    archive: Archive,
    worktreeName: string | null,
    worktreePath: string | null,
  ): ArchivedTask {
    const repository =
      !archive.repository && workspace.repositoryId
        ? this.repositoryRepo.findById(workspace.repositoryId)
        : null;
    return {
      taskId: workspace.taskId,
      archivedAt: archive.archivedAt,
      folderId: workspace.repositoryId ?? "",
      mode: workspace.mode,
      worktreeName,
      branchName: archive.branchName,
      checkpointId: archive.checkpointId,
      title:
        archive.title ??
        this.unknownTaskTitle(
          workspace.taskId,
          archive.branchName,
          worktreeName,
        ),
      taskCreatedAt: archive.taskCreatedAt ?? workspace.createdAt,
      repository: archive.repository ?? repository?.path ?? worktreePath,
      recoveryPending: !archive.title,
    };
  }

  private unknownTaskTitle(
    taskId: string,
    branchName: string | null,
    worktreeName: string | null,
  ): string {
    return `Unknown task (${branchName ?? worktreeName ?? taskId.slice(0, 8)})`;
  }

  private deriveWorktreePath(folderPath: string, worktreeName: string): string {
    return deriveWorktreePathFromBase(
      this.workspaceSettings.getWorktreeLocation(),
      folderPath,
      worktreeName,
    );
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
    archive: Archive,
    recreateBranch?: boolean,
  ): Promise<string> {
    if (!archive.checkpointId) {
      throw new Error("checkpointId is required for restoring worktree");
    }
    const worktree = this.worktreeRepo.findByWorkspaceId(workspace.id);

    const newWorktree = await restoreWorktreeFromCheckpoint({
      mainRepoPath: folderPath,
      worktreeBasePath: this.workspaceSettings.getWorktreeLocation(),
      preferredName: worktree?.name ?? undefined,
      branchName: archive.branchName,
      checkpointId: archive.checkpointId,
      recreateBranch,
      logger: this.log,
    });

    if (worktree) {
      this.worktreeRepo.deleteByWorkspaceId(workspace.id);
    }

    return newWorktree.worktreeName;
  }
}
