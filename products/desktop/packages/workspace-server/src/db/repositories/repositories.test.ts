import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DatabaseService } from "../service";
import { createTestDb, type TestDatabase } from "../test-helpers";
import { RepositoryRepository } from "./repository-repository";
import { WorkspaceRepository } from "./workspace-repository";
import { WorktreeRepository } from "./worktree-repository";

let testDb: TestDatabase;
let repositories: RepositoryRepository;
let workspaces: WorkspaceRepository;
let worktrees: WorktreeRepository;

beforeEach(() => {
  testDb = createTestDb();
  const databaseService = { db: testDb.db } as unknown as DatabaseService;
  repositories = new RepositoryRepository(databaseService);
  workspaces = new WorkspaceRepository(databaseService);
  worktrees = new WorktreeRepository(databaseService);
});

afterEach(() => {
  testDb.close();
});

describe("RepositoryRepository round-trip", () => {
  it("persists a created repository and reads it back by id", () => {
    const created = repositories.create({
      path: "/repos/twig",
      remoteUrl: "posthog/twig",
    });

    const found = repositories.findById(created.id);

    expect(found).not.toBeNull();
    expect(found?.path).toBe("/repos/twig");
    expect(found?.remoteUrl).toBe("posthog/twig");
  });

  it("finds a repository by path", () => {
    const created = repositories.create({ path: "/repos/twig" });

    expect(repositories.findByPath("/repos/twig")?.id).toBe(created.id);
  });

  it("updates the remote url in place", () => {
    const created = repositories.create({ path: "/repos/twig" });

    repositories.updateRemoteUrl(created.id, "posthog/twig");

    expect(repositories.findById(created.id)?.remoteUrl).toBe("posthog/twig");
  });

  it("removes a deleted repository from reads", () => {
    const created = repositories.create({ path: "/repos/twig" });

    repositories.delete(created.id);

    expect(repositories.findById(created.id)).toBeNull();
  });
});

describe("WorkspaceRepository PR cache accumulation", () => {
  const PR_1 = "https://github.com/acme/repo/pull/1";
  const PR_2 = "https://github.com/acme/repo/pull/2";

  beforeEach(() => {
    workspaces.create({ taskId: "task-1", repositoryId: null, mode: "local" });
  });

  it("appends each new PR URL while keeping first-created order", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: true,
    });
    workspaces.updatePrCache("task-1", {
      prUrl: PR_2,
      prState: "open",
      accumulate: true,
    });

    expect(workspaces.getPrUrls("task-1")).toEqual([PR_1, PR_2]);
    expect(workspaces.findByTaskId("task-1")?.prUrl).toBe(PR_2);
  });

  it("does not duplicate an already-seen PR URL", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: true,
    });
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "merged",
      accumulate: true,
    });

    expect(workspaces.getPrUrls("task-1")).toEqual([PR_1]);
  });

  it("keeps accumulated URLs when the current PR clears", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: true,
    });
    workspaces.updatePrCache("task-1", {
      prUrl: null,
      prState: null,
      accumulate: false,
    });

    expect(workspaces.getPrUrls("task-1")).toEqual([PR_1]);
    expect(workspaces.findByTaskId("task-1")?.prUrl).toBeNull();
  });

  it("reads an untouched row as an empty list", () => {
    expect(workspaces.getPrUrls("task-1")).toEqual([]);
  });

  it("does not accumulate a non-attributable PR, but still shows it as current", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: false,
    });

    expect(workspaces.getPrUrls("task-1")).toEqual([]);
    expect(workspaces.findByTaskId("task-1")?.prUrl).toBe(PR_1);
  });

  it("promotePrUrl moves the chosen URL to the front", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: true,
    });
    workspaces.updatePrCache("task-1", {
      prUrl: PR_2,
      prState: "open",
      accumulate: true,
    });

    workspaces.promotePrUrl("task-1", PR_2);

    expect(workspaces.getPrUrls("task-1")).toEqual([PR_2, PR_1]);
  });

  it("promotePrUrl adds an unseen URL at the front", () => {
    workspaces.updatePrCache("task-1", {
      prUrl: PR_1,
      prState: "open",
      accumulate: true,
    });

    workspaces.promotePrUrl("task-1", PR_2);

    expect(workspaces.getPrUrls("task-1")).toEqual([PR_2, PR_1]);
  });
});

describe("repository → workspace → worktree round-trip", () => {
  it("persists the full ownership chain across repositories", () => {
    const repository = repositories.create({ path: "/repos/twig" });

    const workspace = workspaces.create({
      taskId: "task-1",
      repositoryId: repository.id,
      mode: "worktree",
    });

    const worktree = worktrees.create({
      workspaceId: workspace.id,
      name: "feature-branch",
      path: "/worktrees/twig/feature-branch",
    });

    expect(workspaces.findByTaskId("task-1")?.repositoryId).toBe(repository.id);
    expect(worktrees.findByWorkspaceId(workspace.id)?.id).toBe(worktree.id);
    expect(workspaces.findAllByRepositoryId(repository.id)).toHaveLength(1);
  });
});
