import type {
  Archive,
  CreateArchiveData,
  IArchiveRepository,
} from "./archive-repository";

export interface MockArchiveRepositoryOptions {
  failOnCreate?: boolean;
  failOnDelete?: boolean;
}

export interface MockArchiveRepository extends IArchiveRepository {
  _archives: Map<string, Archive>;
}

export function createMockArchiveRepository(
  opts?: MockArchiveRepositoryOptions,
): MockArchiveRepository {
  const archives = new Map<string, Archive>();
  const workspaceIndex = new Map<string, string>();

  return {
    _archives: archives,
    findById: (id: string) => archives.get(id) ?? null,
    findByWorkspaceId: (workspaceId: string) => {
      const id = workspaceIndex.get(workspaceId);
      return id ? (archives.get(id) ?? null) : null;
    },
    findAll: () => Array.from(archives.values()),
    create: (data: CreateArchiveData) => {
      if (opts?.failOnCreate) {
        throw new Error("Injected failure on archive create");
      }
      const now = new Date().toISOString();
      const archive: Archive = {
        id: crypto.randomUUID(),
        workspaceId: data.workspaceId,
        branchName: data.branchName,
        checkpointId: data.checkpointId,
        title: data.title ?? null,
        taskCreatedAt: data.taskCreatedAt ?? null,
        repository: data.repository ?? null,
        archivedAt: now,
        createdAt: now,
        updatedAt: now,
      };
      archives.set(archive.id, archive);
      workspaceIndex.set(archive.workspaceId, archive.id);
      return archive;
    },
    updateDetailsByWorkspaceId: (workspaceId, details) => {
      const id = workspaceIndex.get(workspaceId);
      const archive = id ? archives.get(id) : undefined;
      if (archive) {
        archives.set(archive.id, {
          ...archive,
          ...details,
          updatedAt: new Date().toISOString(),
        });
      }
    },
    deleteByWorkspaceId: (workspaceId: string) => {
      if (opts?.failOnDelete) {
        throw new Error("Injected failure on archive delete");
      }
      const id = workspaceIndex.get(workspaceId);
      if (id) {
        archives.delete(id);
        workspaceIndex.delete(workspaceId);
      }
    },
    deleteAll: () => {
      archives.clear();
      workspaceIndex.clear();
    },
  };
}
