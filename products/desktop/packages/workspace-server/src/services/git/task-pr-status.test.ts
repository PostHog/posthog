import fs from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { WorkspaceService } from "../workspace/workspace";
import type { GitService } from "./service";
import { TaskPrStatusService } from "./task-pr-status";

describe("TaskPrStatusService.getTaskPrStatus (missing worktree directory)", () => {
  let service: TaskPrStatusService;
  let gitService: {
    getDiffStats: ReturnType<typeof vi.fn>;
    getGitSyncStatus: ReturnType<typeof vi.fn>;
  };
  let workspaceService: {
    getWorkspace: ReturnType<typeof vi.fn>;
    emit: ReturnType<typeof vi.fn>;
  };
  let workspaceRepo: {
    findByTaskId: ReturnType<typeof vi.fn>;
    updatePrCache: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    gitService = { getDiffStats: vi.fn(), getGitSyncStatus: vi.fn() };
    workspaceService = { getWorkspace: vi.fn(), emit: vi.fn() };
    workspaceRepo = {
      findByTaskId: vi.fn().mockReturnValue(null),
      updatePrCache: vi.fn(),
    };
    service = new TaskPrStatusService(
      gitService as unknown as GitService,
      workspaceRepo as unknown as IWorkspaceRepository,
      workspaceService as unknown as WorkspaceService,
    );
  });

  it("returns no diff and never touches git when the worktree directory is gone", async () => {
    workspaceService.getWorkspace.mockResolvedValue({
      mode: "worktree",
      worktreePath: "/some/worktree",
      folderPath: null,
      linkedBranch: null,
    });
    vi.spyOn(fs, "existsSync").mockReturnValue(false);

    const result = await service.getTaskPrStatus("task-1", null);
    await new Promise((resolve) => setImmediate(resolve));

    expect(result).toEqual({ prState: null, hasDiff: false });
    expect(gitService.getDiffStats).not.toHaveBeenCalled();
  });
});

describe("TaskPrStatusService revalidation PR detection", () => {
  let service: TaskPrStatusService;
  let gitService: {
    getPrStatus: ReturnType<typeof vi.fn>;
    getDiffStats: ReturnType<typeof vi.fn>;
    getGitSyncStatus: ReturnType<typeof vi.fn>;
    getPrUrlForBranch: ReturnType<typeof vi.fn>;
    getPrDetailsByUrl: ReturnType<typeof vi.fn>;
  };
  let workspaceService: {
    getWorkspace: ReturnType<typeof vi.fn>;
    emit: ReturnType<typeof vi.fn>;
  };
  let workspaceRepo: {
    findByTaskId: ReturnType<typeof vi.fn>;
    updatePrCache: ReturnType<typeof vi.fn>;
    getPrUrls: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    gitService = {
      getPrStatus: vi.fn(),
      getDiffStats: vi.fn().mockResolvedValue({ filesChanged: 0 }),
      getGitSyncStatus: vi.fn().mockResolvedValue({ aheadOfDefault: 0 }),
      getPrUrlForBranch: vi.fn(),
      getPrDetailsByUrl: vi.fn(),
    };
    workspaceService = { getWorkspace: vi.fn(), emit: vi.fn() };
    workspaceRepo = {
      findByTaskId: vi.fn().mockReturnValue({ prUrl: null, prState: null }),
      updatePrCache: vi.fn(),
      getPrUrls: vi
        .fn()
        .mockReturnValue(["https://github.com/acme/repo/pull/7"]),
    };
    service = new TaskPrStatusService(
      gitService as unknown as GitService,
      workspaceRepo as unknown as IWorkspaceRepository,
      workspaceService as unknown as WorkspaceService,
    );
    vi.spyOn(fs, "existsSync").mockReturnValue(true);
  });

  it.each([
    {
      name: "detects a PR on a local task's current branch with no linked branch",
      taskId: "task-local",
      workspace: { mode: "local", worktreePath: null, folderPath: "/repo" },
      prStatus: {
        prExists: true,
        prState: "open",
        prUrl: "https://github.com/acme/repo/pull/7",
        isDraft: false,
      },
      diffStats: { filesChanged: 0 },
      expectedRepoPath: "/repo",
      expectDiffStatsCalled: false,
      expectedCache: {
        prUrl: "https://github.com/acme/repo/pull/7",
        prState: "open",
        accumulate: false,
      },
      expectedEmit: {
        prUrl: "https://github.com/acme/repo/pull/7",
        prUrls: ["https://github.com/acme/repo/pull/7"],
        prState: "open",
      },
    },
    {
      name: "accumulates a PR detected on a task's dedicated worktree",
      taskId: "task-wt",
      workspace: { mode: "worktree", worktreePath: "/wt", folderPath: null },
      prStatus: {
        prExists: true,
        prState: "open",
        prUrl: "https://github.com/acme/repo/pull/7",
        isDraft: false,
      },
      diffStats: { filesChanged: 0 },
      expectedRepoPath: "/wt",
      expectDiffStatsCalled: true,
      expectedCache: {
        prUrl: "https://github.com/acme/repo/pull/7",
        prState: "open",
        accumulate: true,
      },
      expectedEmit: {
        prUrl: "https://github.com/acme/repo/pull/7",
        prUrls: ["https://github.com/acme/repo/pull/7"],
        prState: "open",
      },
    },
    {
      name: "caches no PR for a local task whose branch has none, without checking diff",
      taskId: "task-local",
      workspace: { mode: "local", worktreePath: null, folderPath: "/repo" },
      prStatus: { prExists: false },
      diffStats: { filesChanged: 0 },
      expectedRepoPath: "/repo",
      expectDiffStatsCalled: false,
      expectedCache: { prUrl: null, prState: null, accumulate: false },
      expectedEmit: null,
    },
    {
      name: "still reports a worktree task's local diff when no PR exists",
      taskId: "task-wt",
      workspace: { mode: "worktree", worktreePath: "/wt", folderPath: null },
      prStatus: { prExists: false },
      diffStats: { filesChanged: 3 },
      expectedRepoPath: "/wt",
      expectDiffStatsCalled: true,
      expectedCache: { prUrl: null, prState: null, accumulate: false },
      expectedEmit: null,
    },
  ])(
    "$name",
    async ({
      taskId,
      workspace,
      prStatus,
      diffStats,
      expectedRepoPath,
      expectDiffStatsCalled,
      expectedCache,
      expectedEmit,
    }) => {
      workspaceService.getWorkspace.mockResolvedValue({
        ...workspace,
        linkedBranch: null,
      });
      gitService.getPrStatus.mockResolvedValue(prStatus);
      gitService.getDiffStats.mockResolvedValue(diffStats);

      await service.getTaskPrStatus(taskId, null);
      await new Promise((resolve) => setImmediate(resolve));

      expect(gitService.getPrStatus).toHaveBeenCalledWith(expectedRepoPath);
      if (expectDiffStatsCalled) {
        expect(gitService.getDiffStats).toHaveBeenCalledWith(expectedRepoPath);
      } else {
        expect(gitService.getDiffStats).not.toHaveBeenCalled();
      }
      expect(workspaceRepo.updatePrCache).toHaveBeenCalledWith(
        taskId,
        expectedCache,
      );
      if (expectedEmit) {
        expect(workspaceService.emit).toHaveBeenCalledWith(
          "taskPrInfoChanged",
          {
            taskId,
            ...expectedEmit,
          },
        );
      } else {
        expect(workspaceService.emit).not.toHaveBeenCalled();
      }
    },
  );
});

describe("TaskPrStatusService.setPrimaryPrUrl", () => {
  const PR_OLD = "https://github.com/acme/repo/pull/1";
  const PR_NEW = "https://github.com/acme/repo/pull/2";

  function makeService(getPrDetailsByUrl: ReturnType<typeof vi.fn>) {
    const gitService = { getPrDetailsByUrl } as unknown as GitService;
    const workspaceService = { emit: vi.fn() };
    const workspaceRepo = {
      promotePrUrl: vi.fn(),
      updatePrCache: vi.fn(),
      getPrUrls: vi.fn().mockReturnValue([PR_NEW, PR_OLD]),
    };
    const service = new TaskPrStatusService(
      gitService,
      workspaceRepo as unknown as IWorkspaceRepository,
      workspaceService as unknown as WorkspaceService,
    );
    return { service, workspaceService, workspaceRepo };
  }

  it.each([
    {
      name: "recomputes and emits the promoted PR's live state, not the stale cache",
      details: vi.fn().mockResolvedValue({
        state: "open",
        merged: false,
        draft: false,
      }),
      expectedPrState: "open",
    },
    {
      name: "emits a null state when the promoted PR's details are unavailable",
      details: vi.fn().mockResolvedValue(null),
      expectedPrState: null,
    },
    {
      name: "falls back to a null state when the details fetch rejects",
      details: vi.fn().mockRejectedValue(new Error("network down")),
      expectedPrState: null,
    },
  ])("$name", async ({ details, expectedPrState }) => {
    const { service, workspaceService, workspaceRepo } = makeService(details);

    await service.setPrimaryPrUrl("task-1", PR_NEW);

    expect(workspaceRepo.promotePrUrl).toHaveBeenCalledWith("task-1", PR_NEW);
    expect(details).toHaveBeenCalledWith(PR_NEW);
    expect(workspaceRepo.updatePrCache).toHaveBeenCalledWith("task-1", {
      prUrl: PR_NEW,
      prState: expectedPrState,
      accumulate: false,
    });
    expect(workspaceService.emit).toHaveBeenCalledWith("taskPrInfoChanged", {
      taskId: "task-1",
      prUrl: PR_NEW,
      prUrls: [PR_NEW, PR_OLD],
      prState: expectedPrState,
    });
  });
});
