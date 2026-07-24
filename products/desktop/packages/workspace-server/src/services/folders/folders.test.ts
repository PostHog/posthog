import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockExistsSync = vi.hoisted(() => vi.fn(() => true));
const mockDialog = vi.hoisted(() => ({
  confirm: vi.fn(),
  pickFile: vi.fn(),
}));
const mockRepositoryRepo = vi.hoisted(() => ({
  findAll: vi.fn(),
  findById: vi.fn(),
  findByPath: vi.fn(),
  findByRemoteUrl: vi.fn(),
  findMostRecentlyAccessed: vi.fn(),
  create: vi.fn(),
  upsertByPath: vi.fn(),
  updateLastAccessed: vi.fn(),
  updateRemoteUrl: vi.fn(),
  delete: vi.fn(),
}));
const mockWorkspaceRepo = vi.hoisted(() => ({
  findAllByRepositoryId: vi.fn(),
  findAll: vi.fn(),
}));
const mockWorktreeRepo = vi.hoisted(() => ({
  findByWorkspaceId: vi.fn(),
  findAll: vi.fn(),
}));
const mockWorktreeManager = vi.hoisted(() => ({
  deleteWorktree: vi.fn(),
  cleanupOrphanedWorktrees: vi.fn(),
  sweepTrash: vi.fn(),
}));
const mockInitRepositorySaga = vi.hoisted(() => ({
  run: vi.fn(),
}));

vi.mock("node:fs", () => ({
  existsSync: mockExistsSync,
  promises: {
    readdir: vi.fn(),
    readFile: vi.fn(),
  },
  default: {
    existsSync: mockExistsSync,
    promises: {
      readdir: vi.fn(),
      readFile: vi.fn(),
    },
  },
}));

vi.mock("@posthog/git/worktree", () => ({
  WorktreeManager: class MockWorktreeManager {
    deleteWorktree = mockWorktreeManager.deleteWorktree;
    cleanupOrphanedWorktrees = mockWorktreeManager.cleanupOrphanedWorktrees;
    sweepTrash = mockWorktreeManager.sweepTrash;
  },
}));

vi.mock("@posthog/git/queries", () => ({
  isGitRepository: vi.fn(() => Promise.resolve(true)),
  getRemoteUrl: vi.fn(() => Promise.resolve(null)),
  getLinkedWorktreeMainPath: vi.fn(() => null),
}));

vi.mock("@posthog/git/sagas/init", () => ({
  InitRepositorySaga: class {
    run = mockInitRepositorySaga.run;
  },
}));

import type { RootLogger } from "@posthog/di/logger";
import {
  getLinkedWorktreeMainPath,
  getRemoteUrl,
  isGitRepository,
} from "@posthog/git/queries";
import type { IDialog } from "@posthog/platform/dialog";
import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import type { IRepositoryRepository } from "../../db/repositories/repository-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { IWorktreeRepository } from "../../db/repositories/worktree-repository";
import { FoldersService } from "./folders";

const mockWorkspaceSettings = {
  getWorktreeLocation: () => "/tmp/worktrees",
} as unknown as IWorkspaceSettings;
const scopedLogger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
};
const mockLogger: RootLogger = {
  ...scopedLogger,
  scope: () => scopedLogger,
};

function createService(): FoldersService {
  return new FoldersService(
    mockRepositoryRepo as unknown as IRepositoryRepository,
    mockWorkspaceRepo as unknown as IWorkspaceRepository,
    mockWorktreeRepo as unknown as IWorktreeRepository,
    mockDialog as unknown as IDialog,
    mockWorkspaceSettings,
    mockLogger,
  );
}

describe("FoldersService", () => {
  let service: FoldersService;

  beforeEach(() => {
    vi.clearAllMocks();

    mockRepositoryRepo.findAll.mockReturnValue([]);
    mockWorkspaceRepo.findAllByRepositoryId.mockReturnValue([]);
    mockWorkspaceRepo.findAll.mockReturnValue([]);
    mockWorktreeRepo.findAll.mockReturnValue([]);

    service = createService();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("initialize", () => {
    it("removes folders that no longer exist on disk", async () => {
      mockRepositoryRepo.findAll.mockReturnValue([
        {
          id: "folder-1",
          path: "/gone/project",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ]);
      mockExistsSync.mockReturnValue(false);
      mockRepositoryRepo.findById.mockReturnValue({
        id: "folder-1",
        path: "/gone/project",
      });
      mockWorkspaceRepo.findAllByRepositoryId.mockReturnValue([]);

      createService();
      await vi.waitFor(() => {
        expect(mockRepositoryRepo.delete).toHaveBeenCalledWith("folder-1");
      });
    });

    it("cleans up orphaned worktrees for each existing folder", async () => {
      mockRepositoryRepo.findAll.mockReturnValue([
        {
          id: "folder-1",
          path: "/home/user/project-a",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
        {
          id: "folder-2",
          path: "/home/user/project-b",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ]);
      mockExistsSync.mockReturnValue(true);
      mockWorktreeRepo.findAll.mockReturnValue([]);
      mockWorktreeManager.cleanupOrphanedWorktrees.mockResolvedValue({
        deleted: [],
        errors: [],
      });

      createService();
      await vi.waitFor(() => {
        expect(
          mockWorktreeManager.cleanupOrphanedWorktrees,
        ).toHaveBeenCalledTimes(2);
      });
    });

    it("continues if one folder removal fails", async () => {
      mockRepositoryRepo.findAll.mockReturnValue([
        {
          id: "folder-1",
          path: "/gone/a",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
        {
          id: "folder-2",
          path: "/gone/b",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ]);
      mockExistsSync.mockReturnValue(false);
      mockRepositoryRepo.findById
        .mockReturnValueOnce({ id: "folder-1", path: "/gone/a" })
        .mockReturnValueOnce({ id: "folder-2", path: "/gone/b" });
      mockWorkspaceRepo.findAllByRepositoryId.mockReturnValue([]);
      mockRepositoryRepo.delete
        .mockImplementationOnce(() => {
          throw new Error("db error");
        })
        .mockImplementationOnce(() => undefined);

      createService();
      await vi.waitFor(() => {
        expect(mockRepositoryRepo.delete).toHaveBeenCalledTimes(2);
        expect(mockRepositoryRepo.delete).toHaveBeenCalledWith("folder-2");
      });
    });

    it("continues if one worktree cleanup fails", async () => {
      mockRepositoryRepo.findAll.mockReturnValue([
        {
          id: "folder-1",
          path: "/home/user/project-a",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
        {
          id: "folder-2",
          path: "/home/user/project-b",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ]);
      mockExistsSync.mockReturnValue(true);
      mockWorktreeRepo.findAll.mockReturnValue([]);
      mockWorktreeManager.cleanupOrphanedWorktrees
        .mockRejectedValueOnce(new Error("cleanup error"))
        .mockResolvedValueOnce({ deleted: [], errors: [] });

      createService();
      await vi.waitFor(() => {
        expect(
          mockWorktreeManager.cleanupOrphanedWorktrees,
        ).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe("getFolders", () => {
    it("returns empty array when no folders registered", async () => {
      mockRepositoryRepo.findAll.mockReturnValue([]);

      const result = await service.getFolders();

      expect(result).toEqual([]);
    });

    it("returns folders with exists property", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/project",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);

      const result = await service.getFolders();

      expect(result).toEqual([
        {
          id: "folder-1",
          path: "/home/user/project",
          name: "project",
          remoteUrl: null,
          lastAccessed: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          mainRepoPath: null,
          exists: true,
        },
      ]);
    });

    it("surfaces the main checkout path for a registered linked worktree", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/project-wt",
          remoteUrl: "posthog/project",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);
      vi.mocked(getLinkedWorktreeMainPath).mockReturnValue(
        "/home/user/project",
      );

      const result = await service.getFolders();

      expect(getLinkedWorktreeMainPath).toHaveBeenCalledWith(
        "/home/user/project-wt",
      );
      expect(result[0].mainRepoPath).toBe("/home/user/project");
    });

    it("strips .git suffix from remote repo name in display name (defensive against legacy data)", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/my-billing-fork",
          remoteUrl: "PostHog/billing.git",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);

      const result = await service.getFolders();

      expect(result[0].name).toBe("my-billing-fork (billing)");
    });

    it("uses remote repo name in display name when it differs from local dir", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/ph-tour-demo",
          remoteUrl: "PostHog/hogotchi",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);

      const result = await service.getFolders();

      expect(result[0].name).toBe("ph-tour-demo (hogotchi)");
    });

    it("uses local dir name when it matches remote repo name", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/hogotchi",
          remoteUrl: "PostHog/hogotchi",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);

      const result = await service.getFolders();

      expect(result[0].name).toBe("hogotchi");
    });

    it("uses local dir name when it matches remote repo name case-insensitively", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/home/user/Hogotchi",
          remoteUrl: "PostHog/hogotchi",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(true);

      const result = await service.getFolders();

      expect(result[0].name).toBe("Hogotchi");
    });

    it("marks non-existent folders", async () => {
      const repos = [
        {
          id: "folder-1",
          path: "/nonexistent/path",
          lastAccessedAt: "2024-01-01T00:00:00.000Z",
          createdAt: "2024-01-01T00:00:00.000Z",
          updatedAt: "2024-01-01T00:00:00.000Z",
        },
      ];
      mockRepositoryRepo.findAll.mockReturnValue(repos);
      mockExistsSync.mockReturnValue(false);

      const result = await service.getFolders();

      expect(result[0].exists).toBe(false);
    });
  });

  describe("addFolder", () => {
    it("adds a new folder when it is a git repository", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(true);
      mockRepositoryRepo.findByPath.mockReturnValue(null);
      mockRepositoryRepo.create.mockReturnValue({
        id: "folder-new",
        path: "/home/user/my-project",
        remoteUrl: null,
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });

      const result = await service.addFolder("/home/user/my-project");

      expect(result.name).toBe("my-project");
      expect(result.path).toBe("/home/user/my-project");
      expect(result.exists).toBe(true);
      expect(mockRepositoryRepo.create).toHaveBeenCalledWith({
        path: "/home/user/my-project",
        remoteUrl: undefined,
      });
    });

    it("throws error for invalid folder path", async () => {
      await expect(service.addFolder("")).rejects.toThrow(
        "Invalid folder path",
      );
    });

    it("prompts to initialize git for non-git folder", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(false);
      mockDialog.confirm.mockResolvedValue(0);
      mockInitRepositorySaga.run.mockResolvedValue({
        success: true,
        data: { initialized: true },
      });
      mockRepositoryRepo.findByPath.mockReturnValue(null);
      mockRepositoryRepo.create.mockReturnValue({
        id: "folder-new",
        path: "/home/user/project",
        remoteUrl: null,
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });

      const result = await service.addFolder("/home/user/project");

      expect(mockDialog.confirm).toHaveBeenCalled();
      expect(mockInitRepositorySaga.run).toHaveBeenCalledWith({
        baseDir: "/home/user/project",
        initialCommit: true,
        commitMessage: "Initial commit",
      });
      expect(result.name).toBe("project");
    });

    it("tags a new folder with the supplied remoteUrl override", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(true);
      mockRepositoryRepo.findByPath.mockReturnValue(null);
      mockRepositoryRepo.create.mockReturnValue({
        id: "folder-new",
        path: "/home/user/fork",
        remoteUrl: "PostHog/posthog",
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });

      await service.addFolder("/home/user/fork", {
        remoteUrl: "https://github.com/PostHog/posthog",
      });

      expect(mockRepositoryRepo.create).toHaveBeenCalledWith({
        path: "/home/user/fork",
        remoteUrl: "PostHog/posthog",
      });
    });

    it("normalizes a non-GitHub override and skips the local remote lookup", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(true);
      vi.mocked(getRemoteUrl).mockResolvedValue(
        "https://github.com/SomeoneElse/wrong",
      );
      mockRepositoryRepo.findByPath.mockReturnValue(null);
      mockRepositoryRepo.create.mockReturnValue({
        id: "folder-new",
        path: "/home/user/fork",
        remoteUrl: "https://gitlab.com/PostHog/posthog",
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });

      await service.addFolder("/home/user/fork", {
        remoteUrl: "https://gitlab.com/PostHog/posthog.git",
      });

      expect(mockRepositoryRepo.create).toHaveBeenCalledWith({
        path: "/home/user/fork",
        remoteUrl: "https://gitlab.com/PostHog/posthog",
      });
      expect(getRemoteUrl).not.toHaveBeenCalled();
    });

    it("backfills remoteUrl on an existing folder when override is supplied", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(true);
      const existing = {
        id: "folder-existing",
        path: "/home/user/project",
        remoteUrl: null,
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      };
      mockRepositoryRepo.findByPath.mockReturnValue(existing);
      mockRepositoryRepo.findById.mockReturnValue(existing);

      await service.addFolder("/home/user/project", {
        remoteUrl: "https://github.com/PostHog/posthog",
      });

      expect(mockRepositoryRepo.updateRemoteUrl).toHaveBeenCalledWith(
        "folder-existing",
        "PostHog/posthog",
      );
    });

    it("throws error when user cancels git init", async () => {
      vi.mocked(isGitRepository).mockResolvedValue(false);
      mockDialog.confirm.mockResolvedValue(1);

      await expect(service.addFolder("/home/user/project")).rejects.toThrow(
        "Folder must be a git repository",
      );
    });
  });

  describe("removeFolder", () => {
    it("removes folder from database", async () => {
      mockRepositoryRepo.findById.mockReturnValue({
        id: "folder-1",
        path: "/home/user/project",
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });
      mockWorkspaceRepo.findAllByRepositoryId.mockReturnValue([]);

      await service.removeFolder("folder-1");

      expect(mockRepositoryRepo.delete).toHaveBeenCalledWith("folder-1");
    });

    it("removes associated worktrees", async () => {
      mockRepositoryRepo.findById.mockReturnValue({
        id: "folder-1",
        path: "/home/user/project",
        lastAccessedAt: "2024-01-01T00:00:00.000Z",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
      });
      mockWorkspaceRepo.findAllByRepositoryId.mockReturnValue([
        {
          id: "workspace-1",
          taskId: "task-1",
          repositoryId: "folder-1",
          mode: "worktree",
          state: "active",
        },
      ]);
      mockWorktreeRepo.findByWorkspaceId.mockReturnValue({
        id: "worktree-1",
        workspaceId: "workspace-1",
        name: "code-task-1",
        path: "/tmp/worktrees/project/code-task-1",
        branch: "main",
      });
      mockWorktreeManager.deleteWorktree.mockResolvedValue(undefined);

      await service.removeFolder("folder-1");

      expect(mockWorktreeManager.deleteWorktree).toHaveBeenCalled();
    });
  });

  describe("updateFolderAccessed", () => {
    it("updates lastAccessed timestamp", async () => {
      await service.updateFolderAccessed("folder-1");

      expect(mockRepositoryRepo.updateLastAccessed).toHaveBeenCalledWith(
        "folder-1",
      );
    });
  });

  describe("cleanupOrphanedWorktrees", () => {
    it("delegates to WorktreeManager", async () => {
      mockWorktreeRepo.findAll.mockReturnValue([]);
      mockWorktreeManager.cleanupOrphanedWorktrees.mockResolvedValue({
        deleted: ["/tmp/worktrees/project/orphan-1"],
        errors: [],
      });

      await service.cleanupOrphanedWorktrees("/home/user/project");

      expect(mockWorktreeManager.cleanupOrphanedWorktrees).toHaveBeenCalledWith(
        [],
      );
    });

    it("excludes associated worktrees from cleanup", async () => {
      mockWorktreeRepo.findAll.mockReturnValue([
        {
          id: "worktree-1",
          workspaceId: "workspace-1",
          name: "code-task-1",
          path: "/tmp/worktrees/project/code-task-1",
          branch: "main",
        },
      ]);
      mockWorktreeManager.cleanupOrphanedWorktrees.mockResolvedValue({
        deleted: [],
        errors: [],
      });

      await service.cleanupOrphanedWorktrees("/home/user/project");

      expect(mockWorktreeManager.cleanupOrphanedWorktrees).toHaveBeenCalledWith(
        ["/tmp/worktrees/project/code-task-1"],
      );
    });
  });
});
