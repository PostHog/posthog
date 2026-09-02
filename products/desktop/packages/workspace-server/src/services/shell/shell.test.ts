import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMockRepositoryRepository } from "../../db/repositories/repository-repository.mock";
import { createMockWorkspaceRepository } from "../../db/repositories/workspace-repository.mock";
import { createMockWorktreeRepository } from "../../db/repositories/worktree-repository.mock";
import { ShellEvent } from "./schemas";

const mockPty = vi.hoisted(() => ({
  spawn: vi.fn(),
}));

vi.mock("node-pty", () => mockPty);

const mockExec = vi.hoisted(() =>
  vi.fn(
    (
      _command: string,
      _options: unknown,
      callback: (error: null, stdout: string, stderr: string) => void,
    ) => callback(null, "", ""),
  ),
);

vi.mock("node:child_process", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:child_process")>();
  return { ...original, exec: mockExec };
});

const mockGitQueries = vi.hoisted(() => ({
  getCurrentBranch: vi.fn(async () => "feature-branch"),
  getDefaultBranch: vi.fn(async () => "main"),
}));

vi.mock("@posthog/git/queries", () => mockGitQueries);

import { ShellService } from "./shell";

function createMockPtyProcess() {
  return {
    pid: 1234,
    process: "bash",
    write: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn(),
    onData: vi.fn(() => ({ dispose: vi.fn() })),
    onExit: vi.fn(() => ({ dispose: vi.fn() })),
  };
}

function createService(overrides?: {
  repositoryRepo?: unknown;
  workspaceRepo?: unknown;
  worktreeRepo?: unknown;
}) {
  const processTracking = {
    register: vi.fn(),
    unregister: vi.fn(),
    kill: vi.fn(),
  };
  const logger = {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  };
  const service = new ShellService(
    processTracking as never,
    (overrides?.repositoryRepo ?? {}) as never,
    (overrides?.workspaceRepo ?? {}) as never,
    (overrides?.worktreeRepo ?? {}) as never,
    { getWorktreeLocation: vi.fn(() => "/tmp/worktrees") } as never,
    logger as never,
  );
  return { service, processTracking };
}

describe("ShellService.destroy", () => {
  it("emits an exit event for explicit teardown", async () => {
    mockPty.spawn.mockReturnValue(createMockPtyProcess());
    const { service } = createService();
    const exitHandler = vi.fn();
    service.on(ShellEvent.Exit, exitHandler);

    await service.create("session-1");

    service.destroy("session-1");

    expect(exitHandler).toHaveBeenCalledWith({
      sessionId: "session-1",
      exitCode: 130,
    });
  });

  it("does nothing for non-existent session", () => {
    const { service } = createService();
    expect(() => service.destroy("nonexistent")).not.toThrow();
  });
});

describe("ShellService.createSession workspace env", () => {
  function createWorktreeTaskService(worktreePath: string) {
    const repositoryRepo = createMockRepositoryRepository();
    const workspaceRepo = createMockWorkspaceRepository();
    const worktreeRepo = createMockWorktreeRepository();
    const repo = repositoryRepo.create({ path: "/repos/code" });
    const workspace = workspaceRepo.create({
      taskId: "task-1",
      repositoryId: repo.id,
      mode: "worktree",
    });
    worktreeRepo.create({
      workspaceId: workspace.id,
      name: "spawn-tasks",
      path: worktreePath,
    });
    return createService({ repositoryRepo, workspaceRepo, worktreeRepo });
  }

  function spawnedEnv(): Record<string, string | undefined> {
    return mockPty.spawn.mock.calls[0][2].env;
  }

  beforeEach(() => {
    mockPty.spawn.mockReset();
    mockPty.spawn.mockReturnValue(createMockPtyProcess());
    mockGitQueries.getCurrentBranch.mockResolvedValue("feature-branch");
    mockGitQueries.getDefaultBranch.mockResolvedValue("main");
  });

  it("uses the stored worktree path when it exists on disk", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "shell-test-"));
    try {
      const { service } = createWorktreeTaskService(tempDir);

      await service.createSession({ sessionId: "session-1", taskId: "task-1" });

      expect(spawnedEnv().POSTHOG_CODE_WORKSPACE_PATH).toBe(tempDir);
      expect(mockGitQueries.getCurrentBranch).toHaveBeenCalledWith(tempDir);
    } finally {
      rmSync(tempDir, { recursive: true, force: true });
    }
  });

  it("falls back to the derived path when the stored path is missing", async () => {
    const { service } = createWorktreeTaskService("/does/not/exist");

    await service.createSession({ sessionId: "session-1", taskId: "task-1" });

    const derivedPath = path.join("/tmp/worktrees", "spawn-tasks", "code");
    expect(spawnedEnv().POSTHOG_CODE_WORKSPACE_PATH).toBe(derivedPath);
    expect(mockGitQueries.getCurrentBranch).toHaveBeenCalledWith(derivedPath);
  });

  it("still creates the shell when env construction fails", async () => {
    mockGitQueries.getDefaultBranch.mockRejectedValue(
      new Error("Cannot use simple-git on a directory that does not exist"),
    );
    const { service } = createWorktreeTaskService("/does/not/exist");

    await expect(
      service.createSession({ sessionId: "session-1", taskId: "task-1" }),
    ).resolves.toBeDefined();

    expect(mockPty.spawn).toHaveBeenCalledTimes(1);
    expect(spawnedEnv().POSTHOG_CODE_WORKSPACE_PATH).toBeUndefined();
  });

  it("strips the internal-child markers the workspace-server runs with", async () => {
    // The workspace-server inherits both vars from apps/code (service.ts); a
    // user terminal must inherit neither. ELECTRON_RUN_AS_NODE would make
    // Electron CLIs run as node; POSTHOG_CODE_INTERNAL_CHILD would trip the
    // bootstrap guard so a direct app-binary launch exits(1).
    const saved = {
      runAsNode: process.env.ELECTRON_RUN_AS_NODE,
      internalChild: process.env.POSTHOG_CODE_INTERNAL_CHILD,
    };
    process.env.ELECTRON_RUN_AS_NODE = "1";
    process.env.POSTHOG_CODE_INTERNAL_CHILD = "1";
    try {
      const { service } = createWorktreeTaskService("/does/not/exist");

      await service.createSession({ sessionId: "session-1", taskId: "task-1" });

      expect(spawnedEnv().ELECTRON_RUN_AS_NODE).toBeUndefined();
      expect(spawnedEnv().POSTHOG_CODE_INTERNAL_CHILD).toBeUndefined();
    } finally {
      restoreEnv("ELECTRON_RUN_AS_NODE", saved.runAsNode);
      restoreEnv("POSTHOG_CODE_INTERNAL_CHILD", saved.internalChild);
    }
  });
});

describe("ShellService.execute", () => {
  it("runs commands with the sanitized shell env", async () => {
    const saved = {
      runAsNode: process.env.ELECTRON_RUN_AS_NODE,
      internalChild: process.env.POSTHOG_CODE_INTERNAL_CHILD,
    };
    process.env.ELECTRON_RUN_AS_NODE = "1";
    process.env.POSTHOG_CODE_INTERNAL_CHILD = "1";
    try {
      const { service } = createService();

      await service.execute("/repo", "echo hi");

      const options = mockExec.mock.calls[0][1] as {
        env: Record<string, string>;
      };
      expect(options.env.ELECTRON_RUN_AS_NODE).toBeUndefined();
      expect(options.env.POSTHOG_CODE_INTERNAL_CHILD).toBeUndefined();
      expect(options.env.TERM_PROGRAM).toBe("PostHog");
    } finally {
      restoreEnv("ELECTRON_RUN_AS_NODE", saved.runAsNode);
      restoreEnv("POSTHOG_CODE_INTERNAL_CHILD", saved.internalChild);
    }
  });
});

function restoreEnv(key: string, value: string | undefined): void {
  if (value === undefined) {
    delete process.env[key];
  } else {
    process.env[key] = value;
  }
}
