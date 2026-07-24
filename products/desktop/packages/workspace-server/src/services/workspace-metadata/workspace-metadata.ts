import { inject, injectable } from "inversify";
import {
  TASK_METADATA_REPOSITORY,
  WORKSPACE_REPOSITORY,
} from "../../db/identifiers";
import type { ITaskMetadataRepository } from "../../db/repositories/task-metadata-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";

export interface TaskTimestamps {
  pinnedAt: string | null;
  lastViewedAt: string | null;
  lastActivityAt: string | null;
}

/**
 * Pin / view / activity metadata for tasks — pure projections over the
 * Workspace records. Extracted from the monolithic WorkspaceService so these
 * data operations live next to the repository, with no git/fs/orchestration.
 *
 * A task that owns a `workspaces` row keeps its metadata on that row (unchanged
 * behavior). Repo-less channel tasks (e.g. canvas generation) have no workspace
 * row — their working dir is a scratch dir — so their metadata lives in the
 * dedicated `task_metadata` table instead. Without it, `markViewed` would write
 * to zero rows and the viewed state would be forgotten on reload.
 */
@injectable()
export class WorkspaceMetadataService {
  constructor(
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: IWorkspaceRepository,
    @inject(TASK_METADATA_REPOSITORY)
    private readonly taskMetadataRepo: ITaskMetadataRepository,
  ) {}

  togglePin(taskId: string): { isPinned: boolean; pinnedAt: string | null } {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    if (workspace) {
      const newPinnedAt = workspace.pinnedAt ? null : new Date().toISOString();
      this.workspaceRepo.updatePinnedAt(taskId, newPinnedAt);
      return { isPinned: newPinnedAt !== null, pinnedAt: newPinnedAt };
    }
    // Rowless task: fall back to the task_metadata table.
    const existing = this.taskMetadataRepo.findByTaskId(taskId);
    const newPinnedAt = existing?.pinnedAt ? null : new Date().toISOString();
    this.taskMetadataRepo.upsert(taskId, { pinnedAt: newPinnedAt });
    return { isPinned: newPinnedAt !== null, pinnedAt: newPinnedAt };
  }

  markViewed(taskId: string): void {
    const lastViewedAt = new Date().toISOString();
    if (this.workspaceRepo.findByTaskId(taskId)) {
      this.workspaceRepo.updateLastViewedAt(taskId, lastViewedAt);
      return;
    }
    this.taskMetadataRepo.upsert(taskId, { lastViewedAt });
  }

  markActivity(taskId: string): void {
    const workspace = this.workspaceRepo.findByTaskId(taskId);
    const metadata = workspace ?? this.taskMetadataRepo.findByTaskId(taskId);
    const lastViewedAt = metadata?.lastViewedAt
      ? new Date(metadata.lastViewedAt).getTime()
      : 0;
    const now = Date.now();
    // Activity must read as newer than the last view, or an unread task that
    // the user is actively running would never surface as unread.
    const activityTime = Math.max(now, lastViewedAt + 1);
    const lastActivityAt = new Date(activityTime).toISOString();
    if (workspace) {
      this.workspaceRepo.updateLastActivityAt(taskId, lastActivityAt);
      return;
    }
    this.taskMetadataRepo.upsert(taskId, { lastActivityAt });
  }

  getPinnedTaskIds(): string[] {
    return [
      ...this.workspaceRepo.findAllPinned().map((w) => w.taskId),
      ...this.taskMetadataRepo.findAllPinned().map((m) => m.taskId),
    ];
  }

  getTaskTimestamps(taskId: string): TaskTimestamps {
    const row =
      this.workspaceRepo.findByTaskId(taskId) ??
      this.taskMetadataRepo.findByTaskId(taskId);
    return {
      pinnedAt: row?.pinnedAt ?? null,
      lastViewedAt: row?.lastViewedAt ?? null,
      lastActivityAt: row?.lastActivityAt ?? null,
    };
  }

  getAllTaskTimestamps(): Record<string, TaskTimestamps> {
    const result: Record<string, TaskTimestamps> = {};
    // Rowless metadata first; workspace rows win on the (unexpected) overlap of
    // a task that later gained a workspace row.
    for (const m of this.taskMetadataRepo.findAll()) {
      result[m.taskId] = {
        pinnedAt: m.pinnedAt,
        lastViewedAt: m.lastViewedAt,
        lastActivityAt: m.lastActivityAt,
      };
    }
    for (const w of this.workspaceRepo.findAll()) {
      result[w.taskId] = {
        pinnedAt: w.pinnedAt,
        lastViewedAt: w.lastViewedAt,
        lastActivityAt: w.lastActivityAt,
      };
    }
    return result;
  }
}
