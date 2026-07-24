import fs from "node:fs";
import { inject, injectable } from "inversify";
import { WORKSPACE_REPOSITORY } from "../../db/identifiers";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import { GIT_SERVICE } from "../../di/tokens";
import { WORKSPACE_SERVICE } from "../workspace/identifiers";
import type {
  CachedPrUrlOutput,
  SidebarPrState,
  TaskPrStatus,
} from "../workspace/schemas";
import type { WorkspaceService } from "../workspace/workspace";
import { type GitService, mapPrState } from "./service";

@injectable()
export class TaskPrStatusService {
  private readonly taskPrRevalidations = new Map<string, Promise<void>>();

  constructor(
    @inject(GIT_SERVICE)
    private readonly gitService: GitService,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: IWorkspaceRepository,
    @inject(WORKSPACE_SERVICE)
    private readonly workspaceService: WorkspaceService,
  ) {}

  async getTaskPrStatus(
    taskId: string,
    cloudPrUrl: string | null,
  ): Promise<TaskPrStatus> {
    const cached = this.workspaceRepo.findByTaskId(taskId);
    const cachedPrState: SidebarPrState = cached?.prState ?? null;

    void this.revalidateTaskPrStatus(taskId, cloudPrUrl);

    if (cachedPrState) return { prState: cachedPrState, hasDiff: false };

    const hasDiff = await this.computeWorktreeHasDiff(taskId);
    return { prState: null, hasDiff };
  }

  getCachedPrUrl(taskId: string): CachedPrUrlOutput {
    const row = this.workspaceRepo.findByTaskId(taskId);
    return {
      prUrl: row?.prUrl ?? null,
      prUrls: this.workspaceRepo.getPrUrls(taskId),
    };
  }

  async setPrimaryPrUrl(taskId: string, prUrl: string): Promise<void> {
    this.workspaceRepo.promotePrUrl(taskId, prUrl);
    const details = await this.gitService
      .getPrDetailsByUrl(prUrl)
      .catch(() => null);
    const prState: SidebarPrState = details
      ? mapPrState(details.state, details.merged, details.draft)
      : null;
    this.workspaceRepo.updatePrCache(taskId, {
      prUrl,
      prState,
      accumulate: false,
    });
    this.workspaceService.emit("taskPrInfoChanged", {
      taskId,
      prUrl,
      prUrls: this.workspaceRepo.getPrUrls(taskId),
      prState,
    });
  }

  private async computeWorktreeHasDiff(taskId: string): Promise<boolean> {
    const workspace = await this.workspaceService.getWorkspace(taskId);
    if (
      !workspace ||
      workspace.mode !== "worktree" ||
      !workspace.worktreePath
    ) {
      return false;
    }
    if (workspace.linkedBranch) return false;
    if (!fs.existsSync(workspace.worktreePath)) return false;
    const [diffStats, syncStatus] = await Promise.all([
      this.gitService.getDiffStats(workspace.worktreePath),
      this.gitService.getGitSyncStatus(workspace.worktreePath),
    ]);
    return (
      (diffStats?.filesChanged ?? 0) > 0 ||
      (syncStatus?.aheadOfDefault ?? 0) > 0
    );
  }

  private async revalidateTaskPrStatus(
    taskId: string,
    cloudPrUrl: string | null,
  ): Promise<void> {
    const inFlight = this.taskPrRevalidations.get(taskId);
    if (inFlight) return inFlight;

    const promise = this.computeTaskPrStatus(taskId, cloudPrUrl)
      .then((fresh) => {
        const cached = this.workspaceRepo.findByTaskId(taskId);
        if (!cached) return;

        const cachedPrUrl = cached.prUrl ?? null;
        const cachedPrState: SidebarPrState = cached.prState ?? null;

        this.workspaceRepo.updatePrCache(taskId, {
          prUrl: fresh.prUrl,
          prState: fresh.prState,
          accumulate: fresh.attributable,
        });

        if (cachedPrUrl === fresh.prUrl && cachedPrState === fresh.prState) {
          return;
        }

        this.workspaceService.emit("taskPrInfoChanged", {
          taskId,
          prUrl: fresh.prUrl,
          prUrls: this.workspaceRepo.getPrUrls(taskId),
          prState: fresh.prState,
        });
      })
      .catch(() => {})
      .finally(() => {
        this.taskPrRevalidations.delete(taskId);
      });

    this.taskPrRevalidations.set(taskId, promise);
    return promise;
  }

  private async computeTaskPrStatus(
    taskId: string,
    cloudPrUrl: string | null,
  ): Promise<{
    prUrl: string | null;
    prState: SidebarPrState;
    hasDiff: boolean;
    attributable: boolean;
  }> {
    const workspace = await this.workspaceService.getWorkspace(taskId);
    if (!workspace) {
      return {
        prUrl: null,
        prState: null,
        hasDiff: false,
        attributable: false,
      };
    }

    const { mode, worktreePath, folderPath, linkedBranch } = workspace;
    const isCloud = mode === "cloud";
    const repoPath = worktreePath ?? (folderPath || null);

    if (isCloud && cloudPrUrl) {
      const details = await this.gitService.getPrDetailsByUrl(cloudPrUrl);
      if (details) {
        return {
          prUrl: cloudPrUrl,
          prState: mapPrState(details.state, details.merged, details.draft),
          hasDiff: false,
          attributable: true,
        };
      }
      return {
        prUrl: cloudPrUrl,
        prState: null,
        hasDiff: false,
        attributable: true,
      };
    }

    if (isCloud) {
      return {
        prUrl: null,
        prState: null,
        hasDiff: false,
        attributable: false,
      };
    }

    if (repoPath && !fs.existsSync(repoPath)) {
      return {
        prUrl: null,
        prState: null,
        hasDiff: false,
        attributable: false,
      };
    }

    if (linkedBranch && repoPath) {
      const prUrl = await this.gitService.getPrUrlForBranch(
        repoPath,
        linkedBranch,
      );
      if (prUrl) {
        const details = await this.gitService.getPrDetailsByUrl(prUrl);
        if (details) {
          return {
            prUrl,
            prState: mapPrState(details.state, details.merged, details.draft),
            hasDiff: false,
            attributable: true,
          };
        }
      }
      return {
        prUrl: null,
        prState: null,
        hasDiff: false,
        attributable: false,
      };
    }

    if (repoPath) {
      const prStatus = await this.gitService.getPrStatus(repoPath);
      if (prStatus.prExists && prStatus.prState) {
        return {
          prUrl: prStatus.prUrl,
          prState: mapPrState(
            prStatus.prState,
            false,
            prStatus.isDraft ?? false,
          ),
          hasDiff: false,
          attributable: !!worktreePath,
        };
      }

      // Only worktree tasks track local diff/ahead state as a PR-less signal.
      if (worktreePath) {
        const [diffStats, syncStatus] = await Promise.all([
          this.gitService.getDiffStats(worktreePath),
          this.gitService.getGitSyncStatus(worktreePath),
        ]);

        const hasDiff =
          (diffStats?.filesChanged ?? 0) > 0 ||
          (syncStatus?.aheadOfDefault ?? 0) > 0;

        return { prUrl: null, prState: null, hasDiff, attributable: false };
      }
    }

    return { prUrl: null, prState: null, hasDiff: false, attributable: false };
  }
}
