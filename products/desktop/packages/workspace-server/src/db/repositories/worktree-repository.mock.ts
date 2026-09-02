import type {
  CreateWorktreeData,
  IWorktreeRepository,
  Worktree,
} from "./worktree-repository";

export interface MockWorktreeRepositoryOptions {
  failOnCreate?: boolean;
  failOnDelete?: boolean;
}

export interface MockWorktreeRepository extends IWorktreeRepository {
  _worktrees: Map<string, Worktree>;
}

export function createMockWorktreeRepository(
  opts?: MockWorktreeRepositoryOptions,
): MockWorktreeRepository {
  const worktrees = new Map<string, Worktree>();
  const workspaceIndex = new Map<string, string>();

  return {
    _worktrees: worktrees,
    findById: (id: string) => worktrees.get(id) ?? null,
    findByWorkspaceId: (workspaceId: string) => {
      const id = workspaceIndex.get(workspaceId);
      return id ? (worktrees.get(id) ?? null) : null;
    },
    findByPath: (p: string) => {
      for (const w of worktrees.values()) {
        if (w.path === p) return w;
      }
      return null;
    },
    findAll: () => Array.from(worktrees.values()),
    create: (data: CreateWorktreeData) => {
      if (opts?.failOnCreate) {
        throw new Error("Injected failure on worktree create");
      }
      const now = new Date().toISOString();
      const worktree: Worktree = {
        id: crypto.randomUUID(),
        workspaceId: data.workspaceId,
        name: data.name,
        path: data.path,
        createdAt: now,
        updatedAt: now,
      };
      worktrees.set(worktree.id, worktree);
      workspaceIndex.set(worktree.workspaceId, worktree.id);
      return worktree;
    },
    updatePath: (workspaceId: string, path: string) => {
      const id = workspaceIndex.get(workspaceId);
      if (id) {
        const wt = worktrees.get(id);
        if (wt) wt.path = path;
      }
    },
    deleteByWorkspaceId: (workspaceId: string) => {
      if (opts?.failOnDelete) {
        throw new Error("Injected failure on worktree delete");
      }
      const id = workspaceIndex.get(workspaceId);
      if (id) {
        worktrees.delete(id);
        workspaceIndex.delete(workspaceId);
      }
    },
    deleteAll: () => {
      worktrees.clear();
      workspaceIndex.clear();
    },
  };
}
