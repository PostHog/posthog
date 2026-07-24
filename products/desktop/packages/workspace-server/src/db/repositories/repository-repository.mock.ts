import type {
  IRepositoryRepository,
  Repository,
} from "./repository-repository";

export function createMockRepositoryRepository(): IRepositoryRepository {
  const repos = new Map<string, Repository>();
  const pathIndex = new Map<string, string>();
  const remoteUrlIndex = new Map<string, string>();

  return {
    findAll: () => Array.from(repos.values()),
    findById: (id: string) => repos.get(id) ?? null,
    findByPath: (p: string) => {
      const id = pathIndex.get(p);
      return id ? (repos.get(id) ?? null) : null;
    },
    findByRemoteUrl: (remoteUrl: string) => {
      const id = remoteUrlIndex.get(remoteUrl);
      return id ? (repos.get(id) ?? null) : null;
    },
    findMostRecentlyAccessed: () => {
      const all = Array.from(repos.values());
      if (all.length === 0) return null;
      return all.sort((a, b) =>
        (b.lastAccessedAt ?? "").localeCompare(a.lastAccessedAt ?? ""),
      )[0];
    },
    create: (data: { path: string; remoteUrl?: string; id?: string }) => {
      const now = new Date().toISOString();
      const repo: Repository = {
        id: data.id ?? crypto.randomUUID(),
        path: data.path,
        remoteUrl: data.remoteUrl ?? null,
        lastAccessedAt: now,
        createdAt: now,
        updatedAt: now,
      };
      repos.set(repo.id, repo);
      pathIndex.set(repo.path, repo.id);
      if (repo.remoteUrl) {
        remoteUrlIndex.set(repo.remoteUrl, repo.id);
      }
      return repo;
    },
    upsertByPath: (p: string, id?: string) => {
      const existing = pathIndex.get(p);
      if (existing) {
        const repo = repos.get(existing);
        if (!repo) {
          throw new Error(`Repository ${existing} not found`);
        }
        repo.lastAccessedAt = new Date().toISOString();
        return repo;
      }
      const now = new Date().toISOString();
      const repo: Repository = {
        id: id ?? crypto.randomUUID(),
        path: p,
        remoteUrl: null,
        lastAccessedAt: now,
        createdAt: now,
        updatedAt: now,
      };
      repos.set(repo.id, repo);
      pathIndex.set(repo.path, repo.id);
      return repo;
    },
    updateLastAccessed: (id: string) => {
      const repo = repos.get(id);
      if (repo) {
        repo.lastAccessedAt = new Date().toISOString();
      }
    },
    updateRemoteUrl: (id: string, remoteUrl: string) => {
      const repo = repos.get(id);
      if (repo) {
        if (repo.remoteUrl) {
          remoteUrlIndex.delete(repo.remoteUrl);
        }
        repo.remoteUrl = remoteUrl;
        remoteUrlIndex.set(remoteUrl, id);
      }
    },
    delete: (id: string) => {
      const repo = repos.get(id);
      if (repo) {
        pathIndex.delete(repo.path);
        if (repo.remoteUrl) {
          remoteUrlIndex.delete(repo.remoteUrl);
        }
        repos.delete(id);
      }
    },
    deleteAll: () => {
      repos.clear();
      pathIndex.clear();
      remoteUrlIndex.clear();
    },
  };
}
