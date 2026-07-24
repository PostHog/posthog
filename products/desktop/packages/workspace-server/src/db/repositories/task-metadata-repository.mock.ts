import type {
  ITaskMetadataRepository,
  TaskMetadataPatch,
  TaskMetadataRow,
} from "./task-metadata-repository";

export interface MockTaskMetadataRepository extends ITaskMetadataRepository {
  _rows: Map<string, TaskMetadataRow>;
}

export function createMockTaskMetadataRepository(): MockTaskMetadataRepository {
  const rows = new Map<string, TaskMetadataRow>();
  const apply = (taskId: string, patch: TaskMetadataPatch) => {
    const ts = new Date().toISOString();
    const existing = rows.get(taskId);
    // Mirror the SQL upsert: only keys present in the patch are written, so an
    // explicit `null` (e.g. unpin) clears the field rather than being ignored.
    rows.set(taskId, {
      taskId,
      pinnedAt:
        "pinnedAt" in patch
          ? (patch.pinnedAt ?? null)
          : (existing?.pinnedAt ?? null),
      lastViewedAt:
        "lastViewedAt" in patch
          ? (patch.lastViewedAt ?? null)
          : (existing?.lastViewedAt ?? null),
      lastActivityAt:
        "lastActivityAt" in patch
          ? (patch.lastActivityAt ?? null)
          : (existing?.lastActivityAt ?? null),
      archivedAt:
        "archivedAt" in patch
          ? (patch.archivedAt ?? null)
          : (existing?.archivedAt ?? null),
      archivedTitle:
        "archivedTitle" in patch
          ? (patch.archivedTitle ?? null)
          : (existing?.archivedTitle ?? null),
      archivedTaskCreatedAt:
        "archivedTaskCreatedAt" in patch
          ? (patch.archivedTaskCreatedAt ?? null)
          : (existing?.archivedTaskCreatedAt ?? null),
      archivedRepository:
        "archivedRepository" in patch
          ? (patch.archivedRepository ?? null)
          : (existing?.archivedRepository ?? null),
      piSessionFile:
        "piSessionFile" in patch
          ? (patch.piSessionFile ?? null)
          : (existing?.piSessionFile ?? null),
      createdAt: existing?.createdAt ?? ts,
      updatedAt: ts,
    });
  };
  return {
    _rows: rows,
    findByTaskId: (taskId) => rows.get(taskId) ?? null,
    findAll: () => [...rows.values()],
    findAllPinned: () => [...rows.values()].filter((r) => r.pinnedAt != null),
    findAllArchived: () =>
      [...rows.values()].filter((r) => r.archivedAt != null),
    upsert: apply,
    delete: (taskId) => {
      rows.delete(taskId);
    },
  };
}
