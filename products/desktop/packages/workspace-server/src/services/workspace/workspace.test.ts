import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { RootLogger } from "@posthog/di/logger";
import {
  anyBranchRefExists,
  branchExists,
  getCurrentBranch,
  getDefaultBranch,
  hasTrackedFiles,
  remoteBranchExists,
} from "@posthog/git/queries";
import type { IAnalytics } from "@posthog/platform/analytics";
import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockRepositoryRepository } from "../../db/repositories/repository-repository.mock";
import { createMockWorkspaceRepository } from "../../db/repositories/workspace-repository.mock";
import { createMockWorktreeRepository } from "../../db/repositories/worktree-repository.mock";
import type { DatabaseService } from "../../db/service";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import type { SuspensionService } from "../suspension/suspension";
import {
  listLinkedWorktrees,
  resolveLocalWorktreePath,
} from "../worktree-query/worktree-query";
import type {
  WorkspaceAgent,
  WorkspaceFileWatcher,
  WorkspaceFocus,
  WorkspaceProvisioning,
} from "./ports";
import type { CreateWorkspaceInput } from "./schemas";
import { WorkspaceService, WorkspaceServiceEvent } from "./workspace";

vi.mock("@posthog/git/queries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@posthog/git/queries")>();
  return {
    ...actual,
    getDefaultBranch: vi.fn(),
    getCurrentBranch: vi.fn(),
    branchExists: vi.fn(),
    anyBranchRefExists: vi.fn(),
    remoteBranchExists: vi.fn(),
    hasTrackedFiles: vi.fn(),
  };
});

// Neutralize the real git worktree removal so delete tests exercise only the
// service's path resolution and managed-folder cleanup, not actual git/fs ops.
vi.mock("../worktree-query/worktree-query", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../worktree-query/worktree-query")>();
  return {
    ...actual,
    deleteWorktree: vi.fn(async () => {}),
    listTwigWorktrees: vi.fn(),
    listLinkedWorktrees: vi.fn(),
    resolveLocalWorktreePath: vi.fn(async (): Promise<string | null> => null),
  };
});

// WorkspaceService constructs a WorktreeManager internally; stub the git-backed
// creation methods so tests can drive the create-path branches without real git.
const mockWorktreeManager = {
  createWorktree: vi.fn(),
  createWorktreeForExistingBranch: vi.fn(),
  createWorktreeForRemoteBranch: vi.fn(),
};

vi.mock("@posthog/git/worktree", () => ({
  WorktreeManager: class {
    createWorktree = mockWorktreeManager.createWorktree;
    createWorktreeForExistingBranch =
      mockWorktreeManager.createWorktreeForExistingBranch;
    createWorktreeForRemoteBranch =
      mockWorktreeManager.createWorktreeForRemoteBranch;
  },
}));

function createMocks() {
  const databaseService = {
    isInitialized: vi.fn(() => true),
  } as unknown as DatabaseService;
  const agent = {
    cancelSessionsByTaskId: vi.fn(async () => {}),
    onAgentFileActivity: vi.fn(),
  } satisfies WorkspaceAgent;
  const processTracking = {
    killByTaskId: vi.fn(),
  } as unknown as ProcessTrackingService;
  const repositoryRepo = createMockRepositoryRepository();
  const workspaceRepo = createMockWorkspaceRepository();
  const worktreeRepo = createMockWorktreeRepository();
  const suspensionService = {
    suspendLeastRecentIfOverLimit: vi.fn(async () => {}),
  } as unknown as SuspensionService;
  const provisioning = {
    emitOutput: vi.fn(),
  } satisfies WorkspaceProvisioning;
  const fileWatcher = {
    stopWatching: vi.fn(async () => {}),
    onGitStateChanged: vi.fn(),
  } satisfies WorkspaceFileWatcher;
  const focus = {
    onBranchRenamed: vi.fn(),
  } satisfies WorkspaceFocus;
  const workspaceSettings = {
    getWorktreeLocation: () => "/tmp/worktrees",
  } as unknown as IWorkspaceSettings;
  const analytics = {
    track: vi.fn(),
  } as unknown as IAnalytics;
  const scopedLog = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const log: RootLogger = {
    ...scopedLog,
    scope: vi.fn(() => scopedLog),
  };

  return {
    databaseService,
    agent,
    processTracking,
    repositoryRepo,
    workspaceRepo,
    worktreeRepo,
    suspensionService,
    provisioning,
    fileWatcher,
    focus,
    workspaceSettings,
    analytics,
    log,
  };
}

/** Seed a worktree-mode workspace whose stored row carries `name` and `path`. */
function seedWorktreeTask(
  mocks: ReturnType<typeof createMocks>,
  opts: {
    taskId: string;
    repoPath: string;
    name: string;
    worktreePath: string;
  },
): void {
  const repo = mocks.repositoryRepo.create({ path: opts.repoPath });
  const workspace = mocks.workspaceRepo.create({
    taskId: opts.taskId,
    repositoryId: repo.id,
    mode: "worktree",
  });
  mocks.worktreeRepo.create({
    workspaceId: workspace.id,
    name: opts.name,
    path: opts.worktreePath,
  });
}

function makeService(mocks: ReturnType<typeof createMocks>): WorkspaceService {
  return new WorkspaceService(
    mocks.databaseService,
    mocks.agent,
    mocks.processTracking,
    mocks.repositoryRepo,
    mocks.workspaceRepo,
    mocks.worktreeRepo,
    mocks.suspensionService,
    mocks.provisioning,
    mocks.fileWatcher,
    mocks.focus,
    mocks.workspaceSettings,
    mocks.analytics,
    { deleteImportForTask: async () => {} },
    mocks.log,
  );
}

describe("WorkspaceService", () => {
  let mocks: ReturnType<typeof createMocks>;
  let service: WorkspaceService;

  beforeEach(() => {
    mocks = createMocks();
    service = makeService(mocks);
  });

  describe("reconcileCloudWorkspaces", () => {
    it("creates only task ids that have no existing workspace, deduped", async () => {
      mocks.workspaceRepo.create({
        taskId: "existing",
        repositoryId: null,
        mode: "cloud",
      });
      const createCloudMany = vi.spyOn(mocks.workspaceRepo, "createCloudMany");

      const result = await service.reconcileCloudWorkspaces([
        "existing",
        "new-a",
        "new-a",
        "new-b",
      ]);

      expect(result.created.sort()).toEqual(["new-a", "new-b"]);
      expect(createCloudMany).toHaveBeenCalledWith(["new-a", "new-b"]);
    });

    it("returns empty and skips insert when nothing is new", async () => {
      const createCloudMany = vi.spyOn(mocks.workspaceRepo, "createCloudMany");

      const result = await service.reconcileCloudWorkspaces([]);

      expect(result.created).toEqual([]);
      expect(createCloudMany).not.toHaveBeenCalled();
    });
  });

  describe("linkBranch", () => {
    it("persists the link, emits LinkedBranchChanged, and tracks analytics", () => {
      const updateLinkedBranch = vi.spyOn(
        mocks.workspaceRepo,
        "updateLinkedBranch",
      );
      const emitted = vi.fn();
      service.on(WorkspaceServiceEvent.LinkedBranchChanged, emitted);

      service.linkBranch("task-1", "feature/x", "user");

      expect(updateLinkedBranch).toHaveBeenCalledWith("task-1", "feature/x");
      expect(emitted).toHaveBeenCalledWith({
        taskId: "task-1",
        branchName: "feature/x",
      });
      expect(mocks.analytics.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_LINKED,
        expect.objectContaining({
          task_id: "task-1",
          branch_name: "feature/x",
          source: "user",
        }),
      );
    });
  });

  describe("unlinkBranch", () => {
    it("clears the link, emits LinkedBranchChanged null, and tracks analytics", () => {
      const updateLinkedBranch = vi.spyOn(
        mocks.workspaceRepo,
        "updateLinkedBranch",
      );
      const emitted = vi.fn();
      service.on(WorkspaceServiceEvent.LinkedBranchChanged, emitted);

      service.unlinkBranch("task-1", "user");

      expect(updateLinkedBranch).toHaveBeenCalledWith("task-1", null);
      expect(emitted).toHaveBeenCalledWith({
        taskId: "task-1",
        branchName: null,
      });
      expect(mocks.analytics.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_UNLINKED,
        expect.objectContaining({ task_id: "task-1", source: "user" }),
      );
    });
  });

  describe("getWorkspace (stale linked branch healing)", () => {
    const tempDirs: string[] = [];

    beforeEach(() => {
      vi.mocked(anyBranchRefExists).mockReset();
    });

    afterEach(() => {
      for (const dir of tempDirs.splice(0)) {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    });

    /** A fake worktree checkout whose HEAD points at `branch`. */
    function mkWorktreeOn(branch: string): string {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), "stale-link-"));
      tempDirs.push(dir);
      fs.mkdirSync(path.join(dir, ".git"));
      fs.writeFileSync(
        path.join(dir, ".git", "HEAD"),
        `ref: refs/heads/${branch}\n`,
      );
      return dir;
    }

    function seedLinkedTask(linkedBranch: string, currentBranch = "main") {
      seedWorktreeTask(mocks, {
        taskId: "t1",
        repoPath: "/code/myrepo",
        name: "wt",
        worktreePath: mkWorktreeOn(currentBranch),
      });
      service.linkBranch("t1", linkedBranch, "user");
      vi.mocked(mocks.analytics.track).mockClear();
    }

    it.each([
      { branch: "feat/gone", refExists: false, expected: null },
      { branch: "feat/alive", refExists: true, expected: "feat/alive" },
    ])(
      "linkedBranch is $expected when refExists=$refExists",
      async ({ branch, refExists, expected }) => {
        seedLinkedTask(branch);
        vi.mocked(anyBranchRefExists).mockResolvedValue(refExists);

        const workspace = await service.getWorkspace("t1");

        expect(workspace?.linkedBranch).toBe(expected);
      },
    );

    it("emits, tracks, and persists the unlink when refs are gone", async () => {
      seedLinkedTask("feat/gone");
      vi.mocked(anyBranchRefExists).mockResolvedValue(false);
      const emitted = vi.fn();
      service.on(WorkspaceServiceEvent.LinkedBranchChanged, emitted);

      await service.getWorkspace("t1");

      expect(emitted).toHaveBeenCalledWith({ taskId: "t1", branchName: null });
      expect(mocks.analytics.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_UNLINKED,
        expect.objectContaining({ task_id: "t1", source: "auto" }),
      );
      expect(mocks.workspaceRepo.findByTaskId("t1")?.linkedBranch).toBeNull();
    });

    it("skips the check when on the linked branch", async () => {
      seedLinkedTask("main", "main");

      const workspace = await service.getWorkspace("t1");

      expect(workspace?.linkedBranch).toBe("main");
      expect(anyBranchRefExists).not.toHaveBeenCalled();
    });

    it("keeps the link when the staleness check fails", async () => {
      seedLinkedTask("feat/unknown");
      vi.mocked(anyBranchRefExists).mockRejectedValue(new Error("git broke"));

      const workspace = await service.getWorkspace("t1");

      expect(workspace?.linkedBranch).toBe("feat/unknown");
      expect(mocks.analytics.track).not.toHaveBeenCalled();
    });
  });

  describe("getWorkspace (cloud mode)", () => {
    it("projects a cloud workspace without touching git or fs", async () => {
      mocks.workspaceRepo.create({
        taskId: "cloud-task",
        repositoryId: "remote-repo",
        mode: "cloud",
      });

      const workspace = await service.getWorkspace("cloud-task");

      expect(workspace).toMatchObject({
        taskId: "cloud-task",
        folderId: "remote-repo",
        mode: "cloud",
        worktreePath: null,
        worktreeName: null,
        branchName: null,
      });
    });

    it("returns null when no workspace exists for the task", async () => {
      expect(await service.getWorkspace("missing")).toBeNull();
    });
  });

  describe("branch watcher wiring", () => {
    it("subscribes to each upstream source exactly once", () => {
      service.initBranchWatcher();
      service.initBranchWatcher();

      expect(mocks.fileWatcher.onGitStateChanged).toHaveBeenCalledTimes(1);
      expect(mocks.focus.onBranchRenamed).toHaveBeenCalledTimes(1);
      expect(mocks.agent.onAgentFileActivity).toHaveBeenCalledTimes(1);
    });

    it("agent file activity bails without touching the db when it is not initialized", async () => {
      vi.mocked(mocks.databaseService.isInitialized).mockReturnValue(false);
      const findByTaskId = vi.spyOn(mocks.workspaceRepo, "findByTaskId");
      service.initBranchWatcher();
      const handler = vi.mocked(mocks.agent.onAgentFileActivity).mock
        .calls[0][0];

      await (handler({
        taskId: "task-1",
        branchName: "feature/x",
      }) as unknown as Promise<void>);
      expect(findByTaskId).not.toHaveBeenCalled();
    });
  });

  describe("checkWorktreeBranch", () => {
    const mainRepoPath = "/tmp/repo";

    beforeEach(() => {
      vi.mocked(getDefaultBranch).mockResolvedValue("main");
      vi.mocked(getCurrentBranch).mockResolvedValue("main");
      vi.mocked(branchExists).mockResolvedValue(false);
      vi.mocked(remoteBranchExists).mockResolvedValue(false);
      vi.mocked(listLinkedWorktrees).mockResolvedValue([]);
    });

    it.each([
      { status: "trunk", branch: "main", local: false, remote: false },
      { status: "local", branch: "feature/x", local: true, remote: false },
      {
        status: "remote-only",
        branch: "feature/x",
        local: false,
        remote: true,
      },
      { status: "missing", branch: "feature/x", local: false, remote: false },
    ])(
      "classifies '$branch' as $status",
      async ({ status, branch, local, remote }) => {
        vi.mocked(branchExists).mockResolvedValue(local);
        vi.mocked(remoteBranchExists).mockResolvedValue(remote);

        expect(
          await service.checkWorktreeBranch({ mainRepoPath, branch }),
        ).toEqual({
          status,
          existingWorktreePath: null,
          existingWorktreeTaskId: null,
        });
      },
    );

    it("offers an unused worktree on the branch for reuse", async () => {
      vi.mocked(branchExists).mockResolvedValue(true);
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/feature-x/repo",
          head: "abc123",
          branch: "feature/x",
        },
      ]);

      expect(
        await service.checkWorktreeBranch({
          mainRepoPath,
          branch: "feature/x",
        }),
      ).toEqual({
        status: "local",
        existingWorktreePath: "/tmp/worktrees/feature-x/repo",
        existingWorktreeTaskId: null,
      });
    });

    it("offers an unused worktree outside the managed base path for reuse", async () => {
      vi.mocked(branchExists).mockResolvedValue(true);
      // A worktree the user created by hand, well outside the managed base path.
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/Users/me/projects/feature-x",
          head: "abc123",
          branch: "feature/x",
        },
      ]);

      expect(
        await service.checkWorktreeBranch({
          mainRepoPath,
          branch: "feature/x",
        }),
      ).toEqual({
        status: "local",
        existingWorktreePath: "/Users/me/projects/feature-x",
        existingWorktreeTaskId: null,
      });
    });

    it("reports the occupying task instead of offering reuse when the worktree is taken", async () => {
      vi.mocked(branchExists).mockResolvedValue(true);
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/feature-x/repo",
          head: "abc123",
          branch: "feature/x",
        },
      ]);
      // Associate a task with that worktree path so getWorktreeTasks finds it.
      // Occupancy matches on the stored `path` column (set explicitly below),
      // not on anything derived from `name` + repo.
      const folder = mocks.repositoryRepo.create({ path: mainRepoPath });
      const occupantWorkspace = mocks.workspaceRepo.create({
        taskId: "occupant-task",
        repositoryId: folder.id,
        mode: "worktree",
      });
      mocks.worktreeRepo.create({
        workspaceId: occupantWorkspace.id,
        name: "feature-x",
        path: "/tmp/worktrees/feature-x/repo",
      });

      expect(
        await service.checkWorktreeBranch({
          mainRepoPath,
          branch: "feature/x",
        }),
      ).toEqual({
        status: "local",
        existingWorktreePath: null,
        existingWorktreeTaskId: "occupant-task",
      });
    });

    it("does not offer reuse for a worktree on the trunk branch", async () => {
      // Trunk supports many coexisting detached worktrees, so an existing
      // worktree on it must not be offered for reuse.
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/main/repo",
          head: "abc123",
          branch: "main",
        },
      ]);

      expect(
        await service.checkWorktreeBranch({ mainRepoPath, branch: "main" }),
      ).toEqual({
        status: "trunk",
        existingWorktreePath: null,
        existingWorktreeTaskId: null,
      });
    });

    it("falls back to the current branch as trunk when getDefaultBranch fails", async () => {
      vi.mocked(getDefaultBranch).mockRejectedValue(new Error("no remote"));
      vi.mocked(getCurrentBranch).mockResolvedValue("develop");

      expect(
        await service.checkWorktreeBranch({ mainRepoPath, branch: "develop" }),
      ).toEqual({
        status: "trunk",
        existingWorktreePath: null,
        existingWorktreeTaskId: null,
      });
    });
  });

  describe("listAdoptableWorktrees", () => {
    const mainRepoPath = "/tmp/repo";

    beforeEach(() => {
      vi.mocked(listLinkedWorktrees).mockResolvedValue([]);
      vi.mocked(resolveLocalWorktreePath).mockResolvedValue(null);
    });

    it("returns only task-less branch worktrees that are not registered folders", async () => {
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        { worktreePath: "/wt/orphan", head: "a1", branch: "feature/orphan" },
        { worktreePath: "/wt/detached", head: "b2", branch: null },
        {
          worktreePath: "/wt/registered",
          head: "c3",
          branch: "feature/registered",
        },
        { worktreePath: "/wt/tasked", head: "d4", branch: "feature/tasked" },
      ]);
      // A worktree the user registered as its own sidebar folder.
      mocks.repositoryRepo.create({ path: "/wt/registered" });
      // A worktree already owned by a task.
      seedWorktreeTask(mocks, {
        taskId: "task-1",
        repoPath: mainRepoPath,
        name: "tasked",
        worktreePath: "/wt/tasked",
      });

      expect(await service.listAdoptableWorktrees(mainRepoPath)).toEqual([
        { worktreePath: "/wt/orphan", branch: "feature/orphan" },
      ]);
    });

    it("excludes the hidden stash worktree that backgrounds the local checkout", async () => {
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        { worktreePath: "/wt/local-stash", head: "a1", branch: "main" },
        { worktreePath: "/wt/orphan", head: "b2", branch: "feature/orphan" },
      ]);
      vi.mocked(resolveLocalWorktreePath).mockResolvedValue("/wt/local-stash");

      expect(await service.listAdoptableWorktrees(mainRepoPath)).toEqual([
        { worktreePath: "/wt/orphan", branch: "feature/orphan" },
      ]);
    });
  });

  describe("createWorkspace (worktree reuse)", () => {
    const mainRepoPath = "/tmp/repo";

    beforeEach(() => {
      vi.mocked(getDefaultBranch).mockResolvedValue("main");
      vi.mocked(getCurrentBranch).mockResolvedValue("main");
      // This package's vitest config does not reset mocks between tests, so
      // default to no linked worktrees; each test sets its own value.
      vi.mocked(listLinkedWorktrees).mockResolvedValue([]);
      mockWorktreeManager.createWorktree.mockReset();
      mockWorktreeManager.createWorktreeForExistingBranch.mockReset();
      mockWorktreeManager.createWorktreeForRemoteBranch.mockReset();
      // The reuse success path checks whether the worktree has files; pretend it
      // does so the empty-workspace warning branch (and its fs reads) is skipped.
      vi.mocked(hasTrackedFiles).mockResolvedValue(true);
    });

    function reuseInput(taskId: string): CreateWorkspaceInput {
      return {
        taskId,
        mainRepoPath,
        folderId: "folder-1",
        folderPath: mainRepoPath,
        mode: "worktree",
        branch: "feature/x",
        reuseExistingWorktree: true,
      };
    }

    it("reuses an unused worktree and stores its layout-aware name (legacy layout)", async () => {
      // Legacy layout is <base>/<repo>/<name>, so the name is the final segment
      // ("feature-x"), not the parent dir. No task owns it, so reuse proceeds and
      // the recovered name is persisted via worktreeRepo.create.
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/repo/feature-x",
          head: "abc123",
          branch: "feature/x",
        },
      ]);
      const createWorktree = vi.spyOn(mocks.worktreeRepo, "create");

      const workspace = await service.createWorkspace(reuseInput("new-task"));

      expect(workspace.worktree?.worktreeName).toBe("feature-x");
      expect(workspace.worktree?.worktreePath).toBe(
        "/tmp/worktrees/repo/feature-x",
      );
      expect(createWorktree).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "feature-x",
          path: "/tmp/worktrees/repo/feature-x",
        }),
      );
    });

    it("reuses an unused worktree and stores its layout-aware name (new layout)", async () => {
      // New layout is <base>/<name>/<repo>, so the final segment equals the repo
      // name ("repo") and the name is the parent dir ("feature-x"). No task owns
      // it, so reuse proceeds and the recovered name is persisted.
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/feature-x/repo",
          head: "abc123",
          branch: "feature/x",
        },
      ]);
      const createWorktree = vi.spyOn(mocks.worktreeRepo, "create");

      const workspace = await service.createWorkspace(reuseInput("new-task"));

      expect(workspace.worktree?.worktreeName).toBe("feature-x");
      expect(workspace.worktree?.worktreePath).toBe(
        "/tmp/worktrees/feature-x/repo",
      );
      expect(createWorktree).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "feature-x",
          path: "/tmp/worktrees/feature-x/repo",
        }),
      );
    });

    it("fails the create step when the worktree was claimed between preflight and create", async () => {
      vi.mocked(listLinkedWorktrees).mockResolvedValue([
        {
          worktreePath: "/tmp/worktrees/feature-x/repo",
          head: "abc123",
          branch: "feature/x",
        },
      ]);
      // Associate another task with that worktree path so the re-check's
      // getWorktreeTasks finds an occupant. Occupancy matches on the stored
      // `path` column (set explicitly below), same as the checkWorktreeBranch
      // occupied case.
      const folder = mocks.repositoryRepo.create({ path: mainRepoPath });
      const occupantWorkspace = mocks.workspaceRepo.create({
        taskId: "occupant-task",
        repositoryId: folder.id,
        mode: "worktree",
      });
      mocks.worktreeRepo.create({
        workspaceId: occupantWorkspace.id,
        name: "feature-x",
        path: "/tmp/worktrees/feature-x/repo",
      });

      await expect(
        service.createWorkspace(reuseInput("new-task")),
      ).rejects.toThrow(/already used by task occupant-task/);
    });

    it("fails instead of creating a detached worktree when an occupied branch is hit without the reuse flag", async () => {
      // No reuse flag: the upfront reuse path is bypassed (e.g. the preflight
      // check errored), so creation falls through to a branch checkout, and git
      // reports the branch is already used by a worktree. The old behavior
      // silently created a detached duplicate; it must now fail loudly.
      mockWorktreeManager.createWorktreeForExistingBranch.mockRejectedValue(
        new Error("fatal: 'feature/x' is already used by worktree at /wt"),
      );

      await expect(
        service.createWorkspace({
          ...reuseInput("new-task"),
          reuseExistingWorktree: false,
        }),
      ).rejects.toThrow(/already has a worktree checked out/);

      expect(mockWorktreeManager.createWorktree).not.toHaveBeenCalled();
    });
  });

  describe("pending creations", () => {
    afterEach(() => {
      vi.mocked(getCurrentBranch).mockReset();
    });

    function localInput(taskId: string): CreateWorkspaceInput {
      return {
        taskId,
        mainRepoPath: "/repo",
        folderId: "folder-1",
        folderPath: "/repo",
        mode: "local",
        branch: "feature/x",
      };
    }

    it("tracks in-flight creations and clears them when creation settles", async () => {
      let rejectBranch: (error: Error) => void = () => {};
      vi.mocked(getCurrentBranch).mockReturnValue(
        new Promise((_, reject) => {
          rejectBranch = reject;
        }),
      );

      const pending = service.createWorkspace(localInput("task-1"));
      expect(service.pendingCreationCount).toBe(1);

      rejectBranch(new Error("boom"));
      await expect(pending).rejects.toThrow("boom");
      expect(service.pendingCreationCount).toBe(0);
    });

    it("waitForPendingCreations resolves even when creations reject", async () => {
      const rejectors: Array<(error: Error) => void> = [];
      const deferredBranch = () =>
        new Promise<string | null>((_, reject) => {
          rejectors.push(reject);
        });
      vi.mocked(getCurrentBranch)
        .mockReturnValueOnce(deferredBranch())
        .mockReturnValueOnce(deferredBranch());

      const first = service.createWorkspace(localInput("task-1"));
      const second = service.createWorkspace(localInput("task-2"));
      expect(service.pendingCreationCount).toBe(2);

      const wait = service.waitForPendingCreations();
      for (const reject of rejectors) {
        reject(new Error("boom"));
      }

      await expect(wait).resolves.toBeUndefined();
      await expect(first).rejects.toThrow("boom");
      await expect(second).rejects.toThrow("boom");
      expect(service.pendingCreationCount).toBe(0);
    });
  });

  describe("worktree path resolved from the stored row", () => {
    const tempDirs: string[] = [];

    afterEach(() => {
      for (const dir of tempDirs.splice(0)) {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    });

    function mkTemp(prefix: string): string {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
      tempDirs.push(dir);
      return dir;
    }

    it("projects an externally-located worktree from its stored path", async () => {
      const externalPath = "/external/checkout/my-worktree";
      seedWorktreeTask(mocks, {
        taskId: "ext",
        repoPath: "/code/myrepo",
        name: "fancy-slug",
        worktreePath: externalPath,
      });

      expect(await service.getWorkspace("ext")).toMatchObject({
        mode: "worktree",
        worktreePath: externalPath,
        worktreeName: "fancy-slug",
      });
      expect(await service.getWorkspaceInfo("ext")).toMatchObject({
        mode: "worktree",
        worktree: expect.objectContaining({
          worktreePath: externalPath,
          worktreeName: "fancy-slug",
        }),
      });
    });

    it("matches occupancy by the stored path, not a derived one", () => {
      const externalPath = "/external/checkout/my-worktree";
      seedWorktreeTask(mocks, {
        taskId: "ext",
        repoPath: "/code/myrepo",
        name: "fancy-slug",
        worktreePath: externalPath,
      });

      expect(service.getWorktreeTasks(externalPath)).toEqual([
        { taskId: "ext" },
      ]);
      // The name would derive to <base>/<name>/<repo>; that path must not match.
      expect(
        service.getWorktreeTasks("/tmp/worktrees/fancy-slug/myrepo"),
      ).toEqual([]);
    });

    it("verifies existence by the stored external path", async () => {
      const externalPath = mkTemp("external-wt-");
      seedWorktreeTask(mocks, {
        taskId: "ext",
        repoPath: "/code/myrepo",
        name: "fancy-slug",
        worktreePath: externalPath,
      });

      // The on-disk worktree lives at its stored external path; a derived
      // <base>/<name>/<repo> would not exist, so this would report missing.
      expect(await service.verifyWorkspaceExists("ext")).toEqual({
        exists: true,
      });

      fs.rmSync(externalPath, { recursive: true, force: true });
      expect(await service.verifyWorkspaceExists("ext")).toEqual({
        exists: false,
        missingPath: externalPath,
      });
    });

    // Identical setup (empty managed `<base>/<repo>` parent, then delete the only
    // worktree for that repo); only the stored worktree path differs. This proves
    // the cleanup guard discriminates on whether the path is under the base path,
    // rather than always (or never) reclaiming the parent folder.
    it.each([
      {
        label:
          "leaves the managed parent folder alone for an external worktree",
        makeWorktreePath: () => mkTemp("external-wt-"),
        managedParentSurvives: true,
      },
      {
        label:
          "reclaims the empty managed parent folder for a worktree under the base path",
        makeWorktreePath: (base: string) =>
          path.join(base, "some-name", "myrepo"),
        managedParentSurvives: false,
      },
    ])(
      "deleteWorkspace via the stored path $label",
      async ({ makeWorktreePath, managedParentSurvives }) => {
        const base = mkTemp("wt-base-");
        mocks.workspaceSettings.getWorktreeLocation = () => base;

        const repoPath = "/code/myrepo";
        const managedParent = path.join(base, "myrepo");
        fs.mkdirSync(managedParent);

        seedWorktreeTask(mocks, {
          taskId: "task",
          repoPath,
          name: "some-name",
          worktreePath: makeWorktreePath(base),
        });

        await service.deleteWorkspace("task", repoPath);

        expect(fs.existsSync(managedParent)).toBe(managedParentSurvives);
      },
    );
  });
});
