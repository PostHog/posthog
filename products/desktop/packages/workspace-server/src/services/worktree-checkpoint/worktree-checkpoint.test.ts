import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockManager = vi.hoisted(() => ({
  createWorktreeForExistingBranch: vi.fn(),
  createDetachedWorktreeAtCommit: vi.fn(),
}));
const mockRevertRun = vi.hoisted(() => vi.fn());
const mockCaptureRun = vi.hoisted(() => vi.fn());
const mockDeleteCheckpoint = vi.hoisted(() => vi.fn());
const mockCheckoutLocalBranch = vi.hoisted(() => vi.fn());

vi.mock("@posthog/git/worktree", () => ({
  WorktreeManager: class {
    createWorktreeForExistingBranch =
      mockManager.createWorktreeForExistingBranch;
    createDetachedWorktreeAtCommit = mockManager.createDetachedWorktreeAtCommit;
  },
}));

vi.mock("@posthog/git/sagas/checkpoint", () => ({
  RevertCheckpointSaga: class {
    run = mockRevertRun;
  },
  CaptureCheckpointSaga: class {
    run = mockCaptureRun;
  },
  deleteCheckpoint: mockDeleteCheckpoint,
}));

vi.mock("@posthog/git/client", () => ({
  createGitClient: vi.fn(() => ({
    checkoutLocalBranch: mockCheckoutLocalBranch,
  })),
}));

import {
  captureWorktreeCheckpoint,
  restoreWorktreeFromCheckpoint,
} from "./worktree-checkpoint";

const BRANCH_WT = { worktreePath: "/wt/branch" };
const DETACHED_WT = { worktreePath: "/wt/detached" };

const baseParams = {
  mainRepoPath: "/repo",
  worktreeBasePath: "/repo/.worktrees",
  preferredName: "feat",
  branchName: "feat" as string | null,
  checkpointId: "cp-1",
};

beforeEach(() => {
  mockManager.createWorktreeForExistingBranch.mockResolvedValue(BRANCH_WT);
  mockManager.createDetachedWorktreeAtCommit.mockResolvedValue(DETACHED_WT);
  mockRevertRun.mockResolvedValue({ success: true });
  mockCaptureRun.mockResolvedValue({ success: true });
  mockDeleteCheckpoint.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("restoreWorktreeFromCheckpoint", () => {
  it("creates a worktree for the existing branch when not recreating it", async () => {
    const result = await restoreWorktreeFromCheckpoint(baseParams);

    expect(mockManager.createWorktreeForExistingBranch).toHaveBeenCalledWith(
      "feat",
      "feat",
    );
    expect(mockManager.createDetachedWorktreeAtCommit).not.toHaveBeenCalled();
    expect(result).toBe(BRANCH_WT);
  });

  it("creates a detached worktree at HEAD when there is no branch", async () => {
    const result = await restoreWorktreeFromCheckpoint({
      ...baseParams,
      branchName: null,
    });

    expect(mockManager.createDetachedWorktreeAtCommit).toHaveBeenCalledWith(
      "HEAD",
      "feat",
    );
    expect(result).toBe(DETACHED_WT);
  });

  it("reverts the new worktree to the requested checkpoint", async () => {
    await restoreWorktreeFromCheckpoint(baseParams);

    expect(mockRevertRun).toHaveBeenCalledWith({
      baseDir: "/wt/branch",
      checkpointId: "cp-1",
    });
  });

  it("throws when the checkpoint revert fails", async () => {
    mockRevertRun.mockResolvedValue({ success: false, error: "bad patch" });

    await expect(restoreWorktreeFromCheckpoint(baseParams)).rejects.toThrow(
      /failed to apply checkpoint: bad patch/,
    );
  });

  it("recreates the branch after revert when recreateBranch is set", async () => {
    await restoreWorktreeFromCheckpoint({
      ...baseParams,
      recreateBranch: true,
    });

    expect(mockManager.createDetachedWorktreeAtCommit).toHaveBeenCalled();
    expect(mockCheckoutLocalBranch).toHaveBeenCalledWith("feat");
  });

  it("does not recreate the branch on the default path", async () => {
    await restoreWorktreeFromCheckpoint(baseParams);

    expect(mockCheckoutLocalBranch).not.toHaveBeenCalled();
  });
});

describe("captureWorktreeCheckpoint", () => {
  it("clears any stale checkpoint before capturing", async () => {
    await captureWorktreeCheckpoint("/repo", "/wt/branch", "cp-1");

    expect(mockDeleteCheckpoint).toHaveBeenCalledWith(
      expect.anything(),
      "cp-1",
    );
    expect(mockCaptureRun).toHaveBeenCalledWith({
      baseDir: "/wt/branch",
      checkpointId: "cp-1",
    });
  });

  it("captures even when clearing the stale checkpoint throws", async () => {
    mockDeleteCheckpoint.mockRejectedValue(new Error("no such checkpoint"));

    await captureWorktreeCheckpoint("/repo", "/wt/branch", "cp-1");

    expect(mockCaptureRun).toHaveBeenCalledTimes(1);
  });

  it("throws when the capture saga fails", async () => {
    mockCaptureRun.mockResolvedValue({ success: false, error: "dirty index" });

    await expect(
      captureWorktreeCheckpoint("/repo", "/wt/branch", "cp-1"),
    ).rejects.toThrow(/Failed to capture checkpoint: dirty index/);
  });
});
