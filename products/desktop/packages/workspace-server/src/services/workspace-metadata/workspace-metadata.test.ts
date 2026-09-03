import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMockTaskMetadataRepository,
  type MockTaskMetadataRepository,
} from "../../db/repositories/task-metadata-repository.mock";
import { WorkspaceMetadataService } from "./workspace-metadata";

const NOW_ISO = "2026-01-01T00:00:00.000Z";

function createService() {
  const repo = {
    findByTaskId: vi.fn(),
    findAll: vi.fn().mockReturnValue([]),
    findAllPinned: vi.fn().mockReturnValue([]),
    updatePinnedAt: vi.fn(),
    updateLastViewedAt: vi.fn(),
    updateLastActivityAt: vi.fn(),
  };
  const metadataRepo: MockTaskMetadataRepository =
    createMockTaskMetadataRepository();
  const service = new WorkspaceMetadataService(
    repo as never,
    metadataRepo as never,
  );
  return { service, repo, metadataRepo };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(NOW_ISO));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WorkspaceMetadataService.togglePin", () => {
  it("pins an unpinned workspace with the current timestamp", () => {
    const { service, repo } = createService();
    repo.findByTaskId.mockReturnValue({ taskId: "t1", pinnedAt: null });

    expect(service.togglePin("t1")).toEqual({
      isPinned: true,
      pinnedAt: NOW_ISO,
    });
    expect(repo.updatePinnedAt).toHaveBeenCalledWith("t1", NOW_ISO);
  });

  it("unpins an already-pinned workspace", () => {
    const { service, repo } = createService();
    repo.findByTaskId.mockReturnValue({
      taskId: "t1",
      pinnedAt: "2025-01-01T00:00:00.000Z",
    });

    expect(service.togglePin("t1")).toEqual({
      isPinned: false,
      pinnedAt: null,
    });
    expect(repo.updatePinnedAt).toHaveBeenCalledWith("t1", null);
  });

  it("pins a rowless task via the task_metadata table", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findByTaskId.mockReturnValue(undefined);

    expect(service.togglePin("t1")).toEqual({
      isPinned: true,
      pinnedAt: NOW_ISO,
    });
    expect(repo.updatePinnedAt).not.toHaveBeenCalled();
    expect(metadataRepo.findByTaskId("t1")?.pinnedAt).toBe(NOW_ISO);

    // Toggling again unpins it.
    expect(service.togglePin("t1")).toEqual({
      isPinned: false,
      pinnedAt: null,
    });
    expect(metadataRepo.findByTaskId("t1")?.pinnedAt).toBeNull();
  });
});

describe("WorkspaceMetadataService.markViewed", () => {
  it("records the current time on the workspace row when one exists", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findByTaskId.mockReturnValue({ taskId: "t1" });

    service.markViewed("t1");

    expect(repo.updateLastViewedAt).toHaveBeenCalledWith("t1", NOW_ISO);
    expect(metadataRepo.findByTaskId("t1")).toBeNull();
  });

  it("records the view in task_metadata for a rowless task", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findByTaskId.mockReturnValue(undefined);

    service.markViewed("t1");

    expect(repo.updateLastViewedAt).not.toHaveBeenCalled();
    expect(metadataRepo.findByTaskId("t1")?.lastViewedAt).toBe(NOW_ISO);
  });
});

describe("WorkspaceMetadataService.markActivity", () => {
  it("uses the current time when the last viewed time is in the past", () => {
    const { service, repo } = createService();
    repo.findByTaskId.mockReturnValue({
      taskId: "t1",
      lastViewedAt: "2020-01-01T00:00:00.000Z",
    });

    service.markActivity("t1");

    expect(repo.updateLastActivityAt).toHaveBeenCalledWith("t1", NOW_ISO);
  });

  it("clamps activity to one ms after a future last-viewed time", () => {
    const { service, repo } = createService();
    const future = "2027-01-01T00:00:00.000Z";
    repo.findByTaskId.mockReturnValue({ taskId: "t1", lastViewedAt: future });

    service.markActivity("t1");

    const expected = new Date(new Date(future).getTime() + 1).toISOString();
    expect(repo.updateLastActivityAt).toHaveBeenCalledWith("t1", expected);
  });

  it("records activity in task_metadata for a rowless task", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findByTaskId.mockReturnValue(undefined);

    service.markActivity("t1");

    expect(repo.updateLastActivityAt).not.toHaveBeenCalled();
    expect(metadataRepo.findByTaskId("t1")?.lastActivityAt).toBe(NOW_ISO);
  });
});

describe("WorkspaceMetadataService projections", () => {
  it("unions pinned task ids from workspaces and task_metadata", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findAllPinned.mockReturnValue([{ taskId: "a" }, { taskId: "b" }]);
    metadataRepo.upsert("c", { pinnedAt: NOW_ISO });

    expect(service.getPinnedTaskIds()).toEqual(["a", "b", "c"]);
  });

  it("projects timestamps from the workspace row when present", () => {
    const { service, repo } = createService();
    repo.findByTaskId.mockReturnValue({
      taskId: "t1",
      pinnedAt: "2025-01-01T00:00:00.000Z",
      lastViewedAt: null,
      lastActivityAt: null,
    });

    expect(service.getTaskTimestamps("t1")).toEqual({
      pinnedAt: "2025-01-01T00:00:00.000Z",
      lastViewedAt: null,
      lastActivityAt: null,
    });
  });

  it("falls back to task_metadata for a rowless task", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findByTaskId.mockReturnValue(undefined);
    metadataRepo.upsert("t1", { lastViewedAt: NOW_ISO });

    expect(service.getTaskTimestamps("t1")).toEqual({
      pinnedAt: null,
      lastViewedAt: NOW_ISO,
      lastActivityAt: null,
    });
  });

  it("returns all-null timestamps for an unknown task", () => {
    const { service, repo } = createService();
    repo.findByTaskId.mockReturnValue(undefined);

    expect(service.getTaskTimestamps("missing")).toEqual({
      pinnedAt: null,
      lastViewedAt: null,
      lastActivityAt: null,
    });
  });

  it("merges all timestamps, with workspace rows winning on overlap", () => {
    const { service, repo, metadataRepo } = createService();
    repo.findAll.mockReturnValue([
      { taskId: "a", pinnedAt: "p", lastViewedAt: "v", lastActivityAt: "x" },
    ]);
    metadataRepo.upsert("b", { lastViewedAt: "bv" });

    expect(service.getAllTaskTimestamps()).toEqual({
      a: { pinnedAt: "p", lastViewedAt: "v", lastActivityAt: "x" },
      b: { pinnedAt: null, lastViewedAt: "bv", lastActivityAt: null },
    });
  });
});
