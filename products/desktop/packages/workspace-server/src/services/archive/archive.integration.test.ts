import { execSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { WorktreeManager } from "@posthog/git/worktree";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { recoverArchiveDetailsFromLogs } = vi.hoisted(() => ({
  recoverArchiveDetailsFromLogs: vi.fn(),
}));

vi.mock("./archive-recovery", () => ({ recoverArchiveDetailsFromLogs }));

vi.mock("electron", () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => {
      if (name === "home") return os.homedir();
      if (name === "userData") return os.tmpdir();
      return os.tmpdir();
    },
  },
}));

let testWorktreeBasePath = "";

import {
  createMockArchiveRepository,
  type MockArchiveRepository,
} from "@posthog/workspace-server/db/repositories/archive-repository.mock";
import type { IRepositoryRepository } from "@posthog/workspace-server/db/repositories/repository-repository";
import { createMockRepositoryRepository } from "@posthog/workspace-server/db/repositories/repository-repository.mock";
import { createMockSuspensionRepository } from "@posthog/workspace-server/db/repositories/suspension-repository.mock";
import {
  createMockTaskMetadataRepository,
  type MockTaskMetadataRepository,
} from "@posthog/workspace-server/db/repositories/task-metadata-repository.mock";
import {
  createMockWorkspaceRepository,
  type MockWorkspaceRepository,
} from "@posthog/workspace-server/db/repositories/workspace-repository.mock";
import {
  createMockWorktreeRepository,
  type MockWorktreeRepository,
} from "@posthog/workspace-server/db/repositories/worktree-repository.mock";
import { ArchiveService } from "./archive";

async function createTempGitRepo(): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "archive-test-"));
  execSync("git init", { cwd: dir, stdio: "pipe" });
  execSync("git config user.email 'test@test.com'", {
    cwd: dir,
    stdio: "pipe",
  });
  execSync("git config user.name 'Test'", { cwd: dir, stdio: "pipe" });
  execSync("git config commit.gpgsign false", { cwd: dir, stdio: "pipe" });
  await fs.writeFile(path.join(dir, "README.md"), "# Test Repo");
  execSync("git add . && git commit -m 'Initial commit'", {
    cwd: dir,
    stdio: "pipe",
  });
  return dir;
}

async function pathExists(p: string): Promise<boolean> {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

const TASK_ID = "task-1";

interface TestContext {
  service: ArchiveService;
  repositoryRepo: IRepositoryRepository;
  workspaceRepo: MockWorkspaceRepository;
  worktreeRepo: MockWorktreeRepository;
  archiveRepo: MockArchiveRepository;
  taskMetadataRepo: MockTaskMetadataRepository;
  repoPath: string;
  repoId: string;
  worktreeBasePath: string;
  archiveInput: () => { taskId: string };
  setupWorktree: (
    method: "detached" | "branch",
    branchName?: string,
  ) => Promise<{ worktreePath: string; worktreeName: string }>;
  git: (cmd: string) => string;
}

interface CreateTestContextOpts {
  mode?: "local" | "cloud" | "worktree";
  hasWorkspace?: boolean;
  isArchived?: boolean;
  failOnArchiveCreate?: boolean;
  failOnArchiveDelete?: boolean;
  failOnWorktreeCreate?: boolean;
  failOnWorktreeDelete?: boolean;
}

async function withTestContext(
  opts: CreateTestContextOpts,
  fn: (ctx: TestContext) => Promise<void>,
): Promise<void> {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "archive-int-"));
  const repoPath = await createTempGitRepo();
  const worktreeBasePath = path.join(tempDir, "worktrees");
  await fs.mkdir(worktreeBasePath, { recursive: true });

  testWorktreeBasePath = worktreeBasePath;

  const repositoryRepo = createMockRepositoryRepository();
  const workspaceRepo = createMockWorkspaceRepository();
  const worktreeRepo = createMockWorktreeRepository({
    failOnCreate: opts.failOnWorktreeCreate,
    failOnDelete: opts.failOnWorktreeDelete,
  });
  const archiveRepo = createMockArchiveRepository({
    failOnCreate: opts.failOnArchiveCreate,
    failOnDelete: opts.failOnArchiveDelete,
  });

  const repo = repositoryRepo.create({ path: repoPath });
  const repoId = repo.id;

  const mocks = {
    sessionCanceller: { cancelSessionsByTaskId: vi.fn() },
    processTracking: { killByTaskId: vi.fn() },
    fileWatcher: { stopWatching: vi.fn() },
  };
  const workspaceSettings = {
    getWorktreeLocation: () => testWorktreeBasePath,
  };
  const scopedLogger = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const archiveLogger = {
    ...scopedLogger,
    scope: () => scopedLogger,
  };

  const suspensionRepo = createMockSuspensionRepository();
  const taskMetadataRepo = createMockTaskMetadataRepository();

  const service = new ArchiveService(
    mocks.sessionCanceller as never,
    mocks.processTracking as never,
    mocks.fileWatcher as never,
    repositoryRepo as never,
    workspaceRepo as never,
    worktreeRepo as never,
    archiveRepo as never,
    suspensionRepo as never,
    taskMetadataRepo as never,
    workspaceSettings as never,
    { deleteImportForTask: async () => {} },
    archiveLogger as never,
  );

  const git = (cmd: string) =>
    execSync(`git ${cmd}`, {
      cwd: repoPath,
      encoding: "utf8",
      stdio: "pipe",
    }).trim();

  const archiveInput = () => ({ taskId: TASK_ID });

  const setupWorktree = async (
    method: "detached" | "branch",
    branchName?: string,
  ) => {
    const manager = new WorktreeManager({
      mainRepoPath: repoPath,
      worktreeBasePath,
    });
    const result =
      method === "detached"
        ? await manager.createDetachedWorktreeAtCommit("HEAD", "test-wt")
        : await manager.createWorktreeForExistingBranch(
            branchName ?? "",
            "test-wt",
          );

    const workspace = workspaceRepo.create({
      taskId: TASK_ID,
      repositoryId: repoId,
      mode: "worktree",
    });

    worktreeRepo.create({
      workspaceId: workspace.id,
      name: result.worktreeName,
      path: result.worktreePath,
    });

    return result;
  };

  if (opts.hasWorkspace !== false && opts.mode && opts.mode !== "worktree") {
    const workspace = workspaceRepo.create({
      taskId: TASK_ID,
      repositoryId: repoId,
      mode: opts.mode,
    });

    if (opts.isArchived) {
      archiveRepo.create({
        workspaceId: workspace.id,
        branchName: null,
        checkpointId: null,
      });
    }
  }

  const ctx: TestContext = {
    service,
    repositoryRepo,
    workspaceRepo,
    worktreeRepo,
    archiveRepo,
    taskMetadataRepo,
    repoPath,
    repoId,
    worktreeBasePath,
    archiveInput,
    setupWorktree,
    git,
  };

  try {
    await fn(ctx);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
    await fs.rm(repoPath, { recursive: true, force: true });
  }
}

describe("ArchiveService integration", () => {
  beforeEach(() => {
    recoverArchiveDetailsFromLogs.mockReset();
    recoverArchiveDetailsFromLogs.mockResolvedValue([]);
  });

  it("keeps task details after the cloud task is no longer available", () =>
    withTestContext({ mode: "local" }, async (ctx) => {
      await ctx.service.archiveTask({
        taskId: TASK_ID,
        title: "Recoverable task",
        taskCreatedAt: "2026-07-23T10:00:00.000Z",
        repository: "posthog/code",
      });

      expect(ctx.service.getArchivedTasks()[0]).toMatchObject({
        taskId: TASK_ID,
        title: "Recoverable task",
        taskCreatedAt: "2026-07-23T10:00:00.000Z",
        repository: "posthog/code",
      });
    }));

  it("keeps an archive identifiable when no original title can be recovered", () =>
    withTestContext({ mode: "local" }, async (ctx) => {
      await ctx.service.archiveTask({ taskId: TASK_ID });

      expect(ctx.service.getArchivedTasks()[0]).toMatchObject({
        taskId: TASK_ID,
        title: `Unknown task (${TASK_ID.slice(0, 8)})`,
        repository: ctx.repoPath,
      });
    }));

  it("recovers legacy workspace details in the background and keeps the canonical repository", () =>
    withTestContext({ mode: "local", isArchived: true }, async (ctx) => {
      recoverArchiveDetailsFromLogs.mockResolvedValue([
        {
          taskId: TASK_ID,
          title: "Recovered task",
          taskCreatedAt: "2026-07-22T10:00:00.000Z",
          repository: "/tmp/worktrees/code/task-1",
        },
      ]);

      const initial = await ctx.service.listArchivedTasks();

      expect(initial[0]).toMatchObject({ recoveryPending: true });
      await vi.waitFor(() =>
        expect(ctx.archiveRepo.findAll()[0]).toMatchObject({
          title: "Recovered task",
          repository: ctx.repoPath,
        }),
      );
      await expect(ctx.service.listArchivedTasks()).resolves.toEqual([
        expect.objectContaining({
          recoveryPending: false,
          repository: ctx.repoPath,
        }),
      ]);
    }));

  it("persists an honest fallback when rowless details cannot be recovered", () =>
    withTestContext({ hasWorkspace: false }, async (ctx) => {
      await ctx.service.archiveTask({ taskId: "rowless-task" });

      expect(await ctx.service.listArchivedTasks()).toEqual([
        expect.objectContaining({ recoveryPending: true }),
      ]);
      await vi.waitFor(() =>
        expect(ctx.taskMetadataRepo.findByTaskId("rowless-task")).toMatchObject(
          {
            archivedTitle: "Unknown task (rowless-)",
          },
        ),
      );
      await expect(ctx.service.listArchivedTasks()).resolves.toEqual([
        expect.objectContaining({ recoveryPending: false }),
      ]);
    }));

  it("restarts recovery after a later incomplete archive", () =>
    withTestContext({ mode: "local", isArchived: true }, async (ctx) => {
      await ctx.service.listArchivedTasks();
      await vi.waitFor(() =>
        expect(recoverArchiveDetailsFromLogs).toHaveBeenCalledTimes(1),
      );

      await ctx.service.archiveTask({ taskId: "rowless-task" });
      await ctx.service.listArchivedTasks();

      await vi.waitFor(() =>
        expect(recoverArchiveDetailsFromLogs).toHaveBeenCalledTimes(2),
      );
    }));

  describe("worktree mode", () => {
    it("archive and unarchive preserves uncommitted changes", () =>
      withTestContext({}, async (ctx) => {
        const { worktreePath, worktreeName } =
          await ctx.setupWorktree("detached");
        await fs.writeFile(
          path.join(worktreePath, "work.txt"),
          "my precious work",
        );

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(await pathExists(worktreePath)).toBe(false);
        expect(ctx.archiveRepo.findAll()).toHaveLength(1);
        expect(archived.checkpointId).toBeTruthy();

        const result = await ctx.service.unarchiveTask(TASK_ID);

        expect(result.worktreeName).toBe(worktreeName);
        const repoName = path.basename(ctx.repoPath);
        const newWorktreePath = path.join(
          ctx.worktreeBasePath,
          result.worktreeName ?? "",
          repoName,
        );
        expect(await pathExists(newWorktreePath)).toBe(true);

        const content = await fs.readFile(
          path.join(newWorktreePath, "work.txt"),
          "utf8",
        );
        expect(content).toBe("my precious work");

        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
      }));

    it("archive and unarchive preserves branch name", () =>
      withTestContext({}, async (ctx) => {
        const branchName = "feature/my-branch";
        ctx.git(`checkout -b ${branchName}`);
        ctx.git("checkout -");

        const { worktreePath } = await ctx.setupWorktree("branch", branchName);

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(archived.branchName).toBe(branchName);
        expect(await pathExists(worktreePath)).toBe(false);

        await ctx.service.unarchiveTask(TASK_ID);

        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
      }));

    it("unarchive with recreateBranch creates new branch", () =>
      withTestContext({}, async (ctx) => {
        const branchName = "feature/old-branch";
        ctx.git(`checkout -b ${branchName}`);
        ctx.git("checkout -");

        const { worktreePath } = await ctx.setupWorktree("branch", branchName);
        await fs.writeFile(path.join(worktreePath, "work.txt"), "my work");

        await ctx.service.archiveTask(ctx.archiveInput());
        ctx.git(`branch -D ${branchName}`);

        const result = await ctx.service.unarchiveTask(TASK_ID, true);

        const repoName = path.basename(ctx.repoPath);
        const newWorktreePath = path.join(
          ctx.worktreeBasePath,
          result.worktreeName ?? "",
          repoName,
        );

        const currentBranch = execSync("git branch --show-current", {
          cwd: newWorktreePath,
          encoding: "utf8",
          stdio: "pipe",
        }).trim();
        expect(currentBranch).toBe(branchName);

        const content = await fs.readFile(
          path.join(newWorktreePath, "work.txt"),
          "utf8",
        );
        expect(content).toBe("my work");
      }));

    it("archive does not save branch name for detached HEAD", () =>
      withTestContext({}, async (ctx) => {
        const { worktreePath } = await ctx.setupWorktree("detached");

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(archived.branchName).toBeNull();
        expect(await pathExists(worktreePath)).toBe(false);
      }));

    it("throws when trying to archive already archived task", () =>
      withTestContext({}, async (ctx) => {
        await ctx.setupWorktree("detached");

        await ctx.service.archiveTask(ctx.archiveInput());

        await expect(
          ctx.service.archiveTask(ctx.archiveInput()),
        ).rejects.toThrow("already archived");
      }));

    it("archive finds worktree at legacy path format", () =>
      withTestContext({}, async (ctx) => {
        const repoName = path.basename(ctx.repoPath);
        const worktreeName = "legacy-wt";
        const legacyPath = path.join(
          ctx.worktreeBasePath,
          repoName,
          worktreeName,
        );

        await fs.mkdir(legacyPath, { recursive: true });
        ctx.git(`worktree add "${legacyPath}" HEAD --detach`);
        await fs.writeFile(
          path.join(legacyPath, "legacy.txt"),
          "legacy content",
        );

        const workspace = ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: ctx.repoId,
          mode: "worktree",
        });

        ctx.worktreeRepo.create({
          workspaceId: workspace.id,
          name: worktreeName,
          path: legacyPath,
        });

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(archived.checkpointId).toBeTruthy();
        expect(await pathExists(legacyPath)).toBe(false);
      }));

    it("archive succeeds when worktree was deleted externally", () =>
      withTestContext({}, async (ctx) => {
        const { worktreePath } = await ctx.setupWorktree("detached");

        await fs.rm(worktreePath, { recursive: true, force: true });
        expect(await pathExists(worktreePath)).toBe(false);

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(archived.checkpointId).toBeNull();
        expect(archived.branchName).toBeNull();
        expect(ctx.archiveRepo.findAll()).toHaveLength(1);
      }));

    it("archive succeeds when worktree has an in-progress merge conflict", () =>
      withTestContext({}, async (ctx) => {
        const { worktreePath } = await ctx.setupWorktree("detached");

        const wt = (cmd: string) =>
          execSync(`git ${cmd}`, {
            cwd: worktreePath,
            encoding: "utf8",
            stdio: "pipe",
          });

        await fs.writeFile(path.join(worktreePath, "c.txt"), "base\n");
        wt("add c.txt");
        wt("commit -m base");
        wt("tag base_commit");

        await fs.writeFile(path.join(worktreePath, "c.txt"), "AAA\n");
        wt("add c.txt");
        wt("commit -m a");
        wt("tag commit_a");

        wt("reset --hard base_commit");
        await fs.writeFile(path.join(worktreePath, "c.txt"), "BBB\n");
        wt("add c.txt");
        wt("commit -m b");

        wt("merge commit_a || true");

        const archived = await ctx.service.archiveTask(ctx.archiveInput());

        expect(archived.checkpointId).toBeNull();
        expect(await pathExists(worktreePath)).toBe(false);
        expect(ctx.archiveRepo.findAll()).toHaveLength(1);
      }));

    it("archive succeeds and drops the checkpoint when worktree removal fails", () =>
      withTestContext({}, async (ctx) => {
        await ctx.setupWorktree("detached");

        // Simulate git refusing to remove the worktree (e.g. a stale lock).
        // Capture succeeded, so the checkpoint ref exists — but since the
        // worktree stays registered, keeping the restore point would make a
        // later unarchive fail to re-add it. The archive must still be recorded
        // and its checkpoint dropped.
        const deleteSpy = vi
          .spyOn(WorktreeManager.prototype, "deleteWorktree")
          .mockRejectedValue(new Error("worktree is locked"));

        try {
          const archived = await ctx.service.archiveTask(ctx.archiveInput());

          expect(deleteSpy).toHaveBeenCalled();
          expect(archived.checkpointId).toBeNull();
          const records = ctx.archiveRepo.findAll();
          expect(records).toHaveLength(1);
          expect(records[0].checkpointId).toBeNull();
        } finally {
          deleteSpy.mockRestore();
        }
      }));
  });

  describe("local/cloud mode", () => {
    it.each(["local", "cloud"] as const)(
      "archive and unarchive %s mode restores correct workspace",
      (mode) =>
        withTestContext({ mode }, async (ctx) => {
          await ctx.service.archiveTask(ctx.archiveInput());

          expect(ctx.archiveRepo.findAll()).toHaveLength(1);

          const result = await ctx.service.unarchiveTask(TASK_ID);

          expect(result.worktreeName).toBeNull();
          expect(ctx.archiveRepo.findAll()).toHaveLength(0);
        }),
    );
  });

  describe("error handling", () => {
    it("archives task without workspace association", () =>
      withTestContext({ hasWorkspace: false }, async (ctx) => {
        const result = await ctx.service.archiveTask({
          taskId: "nonexistent",
        });
        expect(result).toMatchObject({
          taskId: "nonexistent",
          folderId: "",
          mode: "cloud",
          worktreeName: null,
          branchName: null,
          checkpointId: null,
        });
        // The archive must persist for a rowless task — otherwise the sidebar
        // never learns it's archived and the row reappears on the next refetch.
        expect(ctx.service.getArchivedTaskIds()).toContain("nonexistent");
        expect(ctx.service.isArchived("nonexistent")).toBe(true);
        expect(ctx.service.getArchivedTasks()).toContainEqual(
          expect.objectContaining({ taskId: "nonexistent", mode: "cloud" }),
        );
      }));

    it("rejects archiving a rowless task that is already archived", () =>
      withTestContext({ hasWorkspace: false }, async (ctx) => {
        await ctx.service.archiveTask({ taskId: "nonexistent" });
        await expect(
          ctx.service.archiveTask({ taskId: "nonexistent" }),
        ).rejects.toThrow("already archived");
      }));

    // Unarchive and delete are parallel "remove a rowless task from the archived
    // list" operations sharing the same arrange step; the per-case `extraAssert`
    // covers what's unique (delete also drops the metadata row, not just the
    // archived flag).
    const rowlessRemovalCases: {
      name: string;
      act: (ctx: TestContext) => Promise<unknown>;
      extraAssert?: (ctx: TestContext) => void;
    }[] = [
      {
        name: "unarchiving clears its archived state",
        act: (ctx) => ctx.service.unarchiveTask("nonexistent"),
      },
      {
        name: "deleting removes its metadata row",
        act: (ctx) => ctx.service.deleteArchivedTask("nonexistent"),
        extraAssert: (ctx) =>
          expect(ctx.taskMetadataRepo.findByTaskId("nonexistent")).toBeNull(),
      },
    ];

    it.each(rowlessRemovalCases)(
      "$name and drops it from the archived list",
      ({ act, extraAssert }) =>
        withTestContext({ hasWorkspace: false }, async (ctx) => {
          await ctx.service.archiveTask({ taskId: "nonexistent" });

          await act(ctx);

          expect(ctx.service.getArchivedTaskIds()).not.toContain("nonexistent");
          expect(ctx.service.isArchived("nonexistent")).toBe(false);
          extraAssert?.(ctx);
        }),
    );

    it("does not double-count a task with both a workspace archive and stale metadata", () =>
      withTestContext({}, async (ctx) => {
        // Task owns a workspace + archive (the authoritative record) yet also
        // carries a lingering archivedAt in task_metadata. It must appear once.
        const workspace = ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: null,
          mode: "cloud",
        });
        ctx.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: null,
          checkpointId: null,
        });
        ctx.taskMetadataRepo.upsert(TASK_ID, {
          archivedAt: new Date().toISOString(),
        });

        expect(
          ctx.service.getArchivedTaskIds().filter((id) => id === TASK_ID),
        ).toHaveLength(1);
        expect(
          ctx.service.getArchivedTasks().filter((t) => t.taskId === TASK_ID),
        ).toHaveLength(1);
      }));

    it("unarchives task without repository association", () =>
      withTestContext({}, async (ctx) => {
        const workspace = ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: null,
          mode: "cloud",
        });
        ctx.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: null,
          checkpointId: null,
        });

        const result = await ctx.service.unarchiveTask(TASK_ID);

        expect(result).toEqual({ taskId: TASK_ID, worktreeName: null });
        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
      }));

    it("throws when workspace not found for unarchive", () =>
      withTestContext({}, async (ctx) => {
        await expect(ctx.service.unarchiveTask("nonexistent")).rejects.toThrow(
          "Workspace not found",
        );
      }));

    it("throws when archived task not found for unarchive", () =>
      withTestContext({ mode: "local", isArchived: false }, async (ctx) => {
        await expect(ctx.service.unarchiveTask(TASK_ID)).rejects.toThrow(
          "Archived task not found",
        );
      }));

    it("throws when repository not found for archive", () =>
      withTestContext({}, async (ctx) => {
        ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: "missing-repo-id",
          mode: "local",
        });

        await expect(
          ctx.service.archiveTask(ctx.archiveInput()),
        ).rejects.toThrow("Repository not found");
      }));

    it("throws when repository not found for unarchive", () =>
      withTestContext({}, async (ctx) => {
        const workspace = ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: "missing-repo-id",
          mode: "worktree",
        });
        ctx.worktreeRepo.create({
          workspaceId: workspace.id,
          name: "test-wt",
          path: "/some/path",
        });
        ctx.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: null,
          checkpointId: "worktree-test-wt",
        });

        await expect(ctx.service.unarchiveTask(TASK_ID)).rejects.toThrow(
          "Repository not found",
        );
      }));
  });

  describe("getters", () => {
    it("getArchivedTasks returns tasks from repository", () =>
      withTestContext({ mode: "local", isArchived: true }, async (ctx) => {
        const tasks = ctx.service.getArchivedTasks();
        expect(tasks).toHaveLength(1);
        expect(tasks[0].taskId).toBe(TASK_ID);

        expect(ctx.service.getArchivedTaskIds()).toEqual([TASK_ID]);
        expect(ctx.service.isArchived(TASK_ID)).toBe(true);
        expect(ctx.service.isArchived("task-2")).toBe(false);
      }));
  });

  describe("deleteArchivedTask", () => {
    it("deletes archived task without checkpoint", () =>
      withTestContext({ mode: "local", isArchived: true }, async (ctx) => {
        await ctx.service.deleteArchivedTask(TASK_ID);
        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
        expect(ctx.workspaceRepo.findByTaskId(TASK_ID)).toBeNull();
      }));

    it("deletes archived task with checkpoint", () =>
      withTestContext({}, async (ctx) => {
        const { worktreePath } = await ctx.setupWorktree("detached");
        await fs.writeFile(path.join(worktreePath, "file.txt"), "content");

        const archived = await ctx.service.archiveTask(ctx.archiveInput());
        expect(archived.checkpointId).toBeTruthy();
        expect(ctx.archiveRepo.findAll()).toHaveLength(1);

        const refs = ctx.git("for-each-ref --format='%(refname)'");
        expect(refs).toContain(archived.checkpointId);

        await ctx.service.deleteArchivedTask(TASK_ID);

        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
        const refsAfter = ctx.git("for-each-ref --format='%(refname)'");
        expect(refsAfter).not.toContain(archived.checkpointId);
      }));

    it("throws when workspace not found for delete", () =>
      withTestContext({}, async (ctx) => {
        await expect(
          ctx.service.deleteArchivedTask("nonexistent"),
        ).rejects.toThrow("Workspace not found");
      }));

    it("throws when archived task not found for delete", () =>
      withTestContext({ mode: "local", isArchived: false }, async (ctx) => {
        await expect(ctx.service.deleteArchivedTask(TASK_ID)).rejects.toThrow(
          "Archived task",
        );
      }));

    it("still removes from repository if checkpoint deletion fails", () =>
      withTestContext({}, async (ctx) => {
        const workspace = ctx.workspaceRepo.create({
          taskId: TASK_ID,
          repositoryId: ctx.repoId,
          mode: "worktree",
        });
        ctx.worktreeRepo.create({
          workspaceId: workspace.id,
          name: "nonexistent",
          path: "/some/path",
        });
        ctx.archiveRepo.create({
          workspaceId: workspace.id,
          branchName: null,
          checkpointId: "worktree-nonexistent",
        });

        await ctx.service.deleteArchivedTask(TASK_ID);
        expect(ctx.archiveRepo.findAll()).toHaveLength(0);
      }));
  });

  describe("rollback behavior", () => {
    it("archive rolls back if archive create fails", () =>
      withTestContext(
        { mode: "local", failOnArchiveCreate: true },
        async (ctx) => {
          await expect(
            ctx.service.archiveTask(ctx.archiveInput()),
          ).rejects.toThrow("Injected failure");

          expect(ctx.archiveRepo.findAll()).toHaveLength(0);
        },
      ));

    it("unarchive rolls back if archive delete fails", () =>
      withTestContext(
        { mode: "local", isArchived: true, failOnArchiveDelete: true },
        async (ctx) => {
          await expect(ctx.service.unarchiveTask(TASK_ID)).rejects.toThrow(
            "Injected failure",
          );

          expect(ctx.archiveRepo.findAll()).toHaveLength(1);
        },
      ));
  });
});
