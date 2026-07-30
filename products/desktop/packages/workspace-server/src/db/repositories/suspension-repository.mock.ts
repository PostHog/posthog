import type {
  CreateSuspensionData,
  Suspension,
  SuspensionRepository,
} from "./suspension-repository";

export interface MockSuspensionRepositoryOptions {
  failOnCreate?: boolean;
  failOnDelete?: boolean;
}

export interface MockSuspensionRepository extends SuspensionRepository {
  _suspensions: Map<string, Suspension>;
}

export function createMockSuspensionRepository(
  opts?: MockSuspensionRepositoryOptions,
): MockSuspensionRepository {
  const suspensions = new Map<string, Suspension>();
  const workspaceIndex = new Map<string, string>();

  return {
    _suspensions: suspensions,
    findById: (id: string) => suspensions.get(id) ?? null,
    findByWorkspaceId: (workspaceId: string) => {
      const id = workspaceIndex.get(workspaceId);
      return id ? (suspensions.get(id) ?? null) : null;
    },
    findAll: () => Array.from(suspensions.values()),
    create: (data: CreateSuspensionData) => {
      if (opts?.failOnCreate) {
        throw new Error("Injected failure on suspension create");
      }
      const now = new Date().toISOString();
      const suspension: Suspension = {
        id: crypto.randomUUID(),
        workspaceId: data.workspaceId,
        branchName: data.branchName,
        checkpointId: data.checkpointId,
        reason: data.reason,
        suspendedAt: now,
        createdAt: now,
        updatedAt: now,
      };
      suspensions.set(suspension.id, suspension);
      workspaceIndex.set(suspension.workspaceId, suspension.id);
      return suspension;
    },
    deleteByWorkspaceId: (workspaceId: string) => {
      if (opts?.failOnDelete) {
        throw new Error("Injected failure on suspension delete");
      }
      const id = workspaceIndex.get(workspaceId);
      if (id) {
        suspensions.delete(id);
        workspaceIndex.delete(workspaceId);
      }
    },
    deleteAll: () => {
      suspensions.clear();
      workspaceIndex.clear();
    },
  };
}
