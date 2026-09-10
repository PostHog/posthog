import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { RootLogger } from "@posthog/di/logger";
import type { IAnalytics } from "@posthog/platform/analytics";
import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockRepositoryRepository } from "../../db/repositories/repository-repository.mock";
import { createMockWorkspaceRepository } from "../../db/repositories/workspace-repository.mock";
import { createMockWorktreeRepository } from "../../db/repositories/worktree-repository.mock";
import type { DatabaseService } from "../../db/service";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import type { SuspensionService } from "../suspension/suspension";
import type {
  WorkspaceAgent,
  WorkspaceFileWatcher,
  WorkspaceFocus,
  WorkspaceProvisioning,
} from "./ports";
import { WorkspaceService } from "./workspace";

const TASK_ID = "task-1";
const REPO_NAME = "posthog";
const WORKTREE_NAME = "plucky-summit-59";

function createService(worktreeBasePath: string) {
  const repositoryRepo = createMockRepositoryRepository();
  const workspaceRepo = createMockWorkspaceRepository();
  const worktreeRepo = createMockWorktreeRepository();

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

  const service = new WorkspaceService(
    { isInitialized: vi.fn(() => true) } as unknown as DatabaseService,
    {
      cancelSessionsByTaskId: vi.fn(async () => {}),
      onAgentFileActivity: vi.fn(),
    } satisfies WorkspaceAgent,
    { killByTaskId: vi.fn() } as unknown as ProcessTrackingService,
    repositoryRepo,
    workspaceRepo,
    worktreeRepo,
    {
      suspendLeastRecentIfOverLimit: vi.fn(async () => {}),
    } as unknown as SuspensionService,
    { emitOutput: vi.fn() } satisfies WorkspaceProvisioning,
    {
      stopWatching: vi.fn(async () => {}),
      onGitStateChanged: vi.fn(),
    } satisfies WorkspaceFileWatcher,
    { onBranchRenamed: vi.fn() } satisfies WorkspaceFocus,
    {
      getWorktreeLocation: () => worktreeBasePath,
    } as unknown as IWorkspaceSettings,
    { track: vi.fn() } as unknown as IAnalytics,
    { deleteImportForTask: async () => {} },
    log,
  );

  return { service, repositoryRepo, workspaceRepo, worktreeRepo };
}

async function exists(p: string): Promise<boolean> {
  try {
    await fsp.access(p);
    return true;
  } catch {
    return false;
  }
}

describe("WorkspaceService.verifyWorkspaceExists", () => {
  let tmpDir: string;
  let worktreeBasePath: string;

  beforeEach(async () => {
    tmpDir = await fsp.mkdtemp(path.join(os.tmpdir(), "ws-verify-"));
    worktreeBasePath = path.join(tmpDir, "worktrees");
  });

  afterEach(async () => {
    await fsp.rm(tmpDir, { recursive: true, force: true });
  });

  it.each([
    { label: "existing worktree", createWorktree: true, expectExists: true },
    { label: "missing worktree", createWorktree: false, expectExists: false },
  ])(
    "$label: reports exists=$expectExists and never deletes the association",
    async ({ createWorktree, expectExists }) => {
      const { service, repositoryRepo, workspaceRepo, worktreeRepo } =
        createService(worktreeBasePath);

      const repoPath = path.join(tmpDir, REPO_NAME);
      const worktreePath = path.join(
        worktreeBasePath,
        WORKTREE_NAME,
        REPO_NAME,
      );
      await fsp.mkdir(repoPath, { recursive: true });
      if (createWorktree) await fsp.mkdir(worktreePath, { recursive: true });

      const repo = repositoryRepo.create({ path: repoPath });
      const workspace = workspaceRepo.create({
        taskId: TASK_ID,
        repositoryId: repo.id,
        mode: "worktree",
      });
      worktreeRepo.create({
        workspaceId: workspace.id,
        name: WORKTREE_NAME,
        path: worktreePath,
      });

      const result = await service.verifyWorkspaceExists(TASK_ID);

      expect(result.exists).toBe(expectExists);
      if (!expectExists) expect(result.missingPath).toContain(WORKTREE_NAME);
      expect(workspaceRepo.findByTaskId(TASK_ID)).not.toBeNull();
      expect(worktreeRepo.findByWorkspaceId(workspace.id)).not.toBeNull();
    },
  );

  it("reports a missing local folder without deleting the association", async () => {
    const { service, repositoryRepo, workspaceRepo } =
      createService(worktreeBasePath);

    const repoPath = path.join(tmpDir, "gone");
    const repo = repositoryRepo.create({ path: repoPath });
    workspaceRepo.create({
      taskId: TASK_ID,
      repositoryId: repo.id,
      mode: "local",
    });

    const result = await service.verifyWorkspaceExists(TASK_ID);

    expect(result.exists).toBe(false);
    expect(result.missingPath).toBe(repoPath);
    expect(workspaceRepo.findByTaskId(TASK_ID)).not.toBeNull();
  });

  it("treats a scratch dir (no workspace row) as a valid local workspace", async () => {
    const { service, workspaceRepo } = createService(worktreeBasePath);

    // No workspace row exists for a repo-less channel task.
    expect(workspaceRepo.findByTaskId(TASK_ID)).toBeNull();

    const scratchPath = await service.ensureScratchDir(TASK_ID);
    expect(scratchPath).toContain("posthog-code-scratch");

    // verify, getWorkspace and getAllWorkspaces all treat it as a local
    // workspace, so the UI resolves a cwd and skips the repo-picker prompt.
    const verify = await service.verifyWorkspaceExists(TASK_ID);
    expect(verify.exists).toBe(true);

    const workspace = await service.getWorkspace(TASK_ID);
    expect(workspace).toMatchObject({
      taskId: TASK_ID,
      mode: "local",
      folderPath: scratchPath,
      worktreePath: null,
      // Marked so the navigation task binder skips folder registration (and the
      // "initialize git" dialog) for repo-less channel tasks.
      isScratch: true,
    });

    const all = await service.getAllWorkspaces();
    expect(all[TASK_ID]?.folderPath).toBe(scratchPath);
    expect(all[TASK_ID]?.isScratch).toBe(true);

    // It is not backed by a DB row.
    expect(workspaceRepo.findByTaskId(TASK_ID)).toBeNull();
  });
});

describe("WorkspaceService scratch path confinement", () => {
  let tmpDir: string;
  let worktreeBasePath: string;

  beforeEach(async () => {
    tmpDir = await fsp.mkdtemp(path.join(os.tmpdir(), "ws-scratch-"));
    worktreeBasePath = path.join(tmpDir, "worktrees");
  });

  afterEach(async () => {
    await fsp.rm(tmpDir, { recursive: true, force: true });
  });

  it("creates then removes a scratch dir for a valid task id", async () => {
    const { service } = createService(worktreeBasePath);

    const scratchPath = await service.ensureScratchDir(TASK_ID);
    expect(await exists(scratchPath)).toBe(true);

    await service.deleteWorkspace(TASK_ID, "");
    expect(await exists(scratchPath)).toBe(false);
  });

  it.each([
    { label: "parent traversal", taskId: ".." },
    { label: "deep traversal", taskId: path.join("..", "..", "victim") },
    { label: "absolute escape", taskId: path.resolve(os.tmpdir(), "victim") },
    { label: "nested path", taskId: path.join("a", "b") },
    { label: "empty id", taskId: "" },
  ])("rejects ensureScratchDir for $label", async ({ taskId }) => {
    const { service } = createService(worktreeBasePath);
    await expect(service.ensureScratchDir(taskId)).rejects.toThrow(
      /invalid scratch task id/i,
    );
  });

  it("never deletes a directory outside the base via a traversal task id", async () => {
    const { service } = createService(worktreeBasePath);

    const victim = path.join(tmpDir, "victim");
    await fsp.mkdir(victim, { recursive: true });
    await fsp.writeFile(path.join(victim, "keep.txt"), "data");

    // "../victim" resolves to <tmpDir>/victim, a sibling of the scratch base.
    await expect(service.deleteWorkspace("../victim", "")).rejects.toThrow(
      /invalid scratch task id/i,
    );
    expect(await exists(path.join(victim, "keep.txt"))).toBe(true);
  });
});
