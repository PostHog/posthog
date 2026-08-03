import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HandoffHostService } from "./service";

function createService(overrides: {
  workspaceRepo?: Partial<{
    findByTaskId: ReturnType<typeof vi.fn>;
    setModeAndRepository: ReturnType<typeof vi.fn>;
    updateMode: ReturnType<typeof vi.fn>;
  }>;
  repositoryRepo?: Partial<{ findByPath: ReturnType<typeof vi.fn> }>;
  git?: object;
  logs?: object;
}) {
  const workspaceRepo = {
    findByTaskId: vi.fn(),
    setModeAndRepository: vi.fn(),
    updateMode: vi.fn(),
    ...overrides.workspaceRepo,
  };
  const repositoryRepo = {
    findByPath: vi.fn(),
    ...overrides.repositoryRepo,
  };
  const git = {
    getChangedFiles: vi.fn(),
    getLocalGitState: vi.fn(),
    cleanupAfterCloudHandoff: vi.fn(),
    ...overrides.git,
  };
  const logs = {
    seedLocalLogs: vi.fn().mockResolvedValue(undefined),
    countLocalLogEntries: vi.fn(),
    deleteLocalLogCache: vi.fn(),
    ...overrides.logs,
  };

  const service = new HandoffHostService(
    {} as never,
    {} as never,
    workspaceRepo as never,
    repositoryRepo as never,
    {} as never,
    {} as never,
    git as never,
    logs as never,
  );
  return { service, workspaceRepo, repositoryRepo, git, logs };
}

describe("HandoffHostService.attachWorkspaceToFolder", () => {
  it("throws when the folder is not registered", () => {
    const { service } = createService({
      repositoryRepo: { findByPath: vi.fn().mockReturnValue(null) },
    });
    expect(() => service.attachWorkspaceToFolder("task-1", "/repo")).toThrow(
      "No registered folder",
    );
  });

  it("throws when the task has no workspace", () => {
    const { service } = createService({
      repositoryRepo: { findByPath: vi.fn().mockReturnValue({ id: "r1" }) },
      workspaceRepo: { findByTaskId: vi.fn().mockReturnValue(null) },
    });
    expect(() => service.attachWorkspaceToFolder("task-1", "/repo")).toThrow(
      "No workspace exists",
    );
  });

  it("is a no-op revert when already local on the same repository", () => {
    const { service, workspaceRepo } = createService({
      repositoryRepo: { findByPath: vi.fn().mockReturnValue({ id: "r1" }) },
      workspaceRepo: {
        findByTaskId: vi
          .fn()
          .mockReturnValue({ mode: "local", repositoryId: "r1" }),
      },
    });
    const { revert } = service.attachWorkspaceToFolder("task-1", "/repo");
    revert();
    expect(workspaceRepo.setModeAndRepository).not.toHaveBeenCalled();
  });

  it("attaches and reverts to the previous mode/repository", () => {
    const { service, workspaceRepo } = createService({
      repositoryRepo: { findByPath: vi.fn().mockReturnValue({ id: "r1" }) },
      workspaceRepo: {
        findByTaskId: vi
          .fn()
          .mockReturnValue({ mode: "cloud", repositoryId: "old" }),
      },
    });
    const { revert } = service.attachWorkspaceToFolder("task-1", "/repo");
    expect(workspaceRepo.setModeAndRepository).toHaveBeenCalledWith(
      "task-1",
      "local",
      "r1",
    );
    revert();
    expect(workspaceRepo.setModeAndRepository).toHaveBeenLastCalledWith(
      "task-1",
      "cloud",
      "old",
    );
  });
});

describe("HandoffHostService.seedLocalLogs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("seeds fetched content into the log gateway", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, text: () => "a\nb\n" }),
    );
    const { service, logs } = createService({});
    await service.seedLocalLogs("run-1", "https://logs");
    expect(logs.seedLocalLogs).toHaveBeenCalledWith("run-1", "a\nb\n");
  });

  it("skips seeding when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const { service, logs } = createService({});
    await service.seedLocalLogs("run-1", "https://logs");
    expect(logs.seedLocalLogs).not.toHaveBeenCalled();
  });

  it("skips seeding when the content is blank", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, text: () => "   " }),
    );
    const { service, logs } = createService({});
    await service.seedLocalLogs("run-1", "https://logs");
    expect(logs.seedLocalLogs).not.toHaveBeenCalled();
  });
});

describe("HandoffHostService delegation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("delegates git + log reads to their gateways", async () => {
    const { service, git, logs } = createService({
      git: {
        getChangedFiles: vi.fn().mockResolvedValue([]),
        getLocalGitState: vi.fn().mockResolvedValue({ branch: "main" }),
      },
      logs: { countLocalLogEntries: vi.fn().mockResolvedValue(3) },
    });
    await service.getChangedFiles("/repo");
    await service.getLocalGitState("/repo");
    await service.countLocalLogEntries("run-1");
    expect(git.getChangedFiles).toHaveBeenCalledWith("/repo");
    expect(git.getLocalGitState).toHaveBeenCalledWith("/repo");
    expect(logs.countLocalLogEntries).toHaveBeenCalledWith("run-1");
  });
});
