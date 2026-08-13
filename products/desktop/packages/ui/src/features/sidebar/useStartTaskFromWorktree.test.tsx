import type { Task } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTaskMock = vi.hoisted(() => vi.fn());
const invalidateTasksMock = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());
const setFailedMock = vi.hoisted(() => vi.fn());
const openTaskMock = vi.hoisted(() => vi.fn());
const trackMock = vi.hoisted(() => vi.fn());
const queryFilterMock = vi.hoisted(() =>
  vi.fn((input: { mainRepoPath: string }) => ({
    queryKey: ["workspace", "listAdoptableWorktrees", input],
  })),
);

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ createTask: createTaskMock }),
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    workspace: { listAdoptableWorktrees: { queryFilter: queryFilterMock } },
  }),
}));
vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useCreateTask: () => ({ invalidateTasks: invalidateTasksMock }),
}));
vi.mock("@posthog/ui/features/notifications/errorDetails", () => ({
  toastError: toastErrorMock,
}));
vi.mock("@posthog/ui/features/provisioning/store", () => ({
  useProvisioningStore: { getState: () => ({ setFailed: setFailedMock }) },
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask: openTaskMock,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({
  track: trackMock,
}));

import { useStartTaskFromWorktree } from "./useStartTaskFromWorktree";

const MAIN_REPO_PATH = "/repo";
const BRANCH = "feature/orphan";

function fakeTask(): Task {
  return {
    id: "task-123",
    task_number: 1,
    slug: "task-123",
    title: BRANCH,
    description: BRANCH,
    created_at: "2026-06-15T00:00:00.000Z",
    updated_at: "2026-06-15T00:00:00.000Z",
    origin_product: "user_created",
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useStartTaskFromWorktree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates the task, opens it, tracks the event, and clears the in-flight branch", async () => {
    const task = fakeTask();
    createTaskMock.mockImplementationOnce(async (_input, onTaskReady) => {
      onTaskReady?.({ task, workspace: null });
      return { success: true, data: { task, workspace: null } };
    });

    const { result } = renderHook(
      () => useStartTaskFromWorktree(MAIN_REPO_PATH),
      {
        wrapper,
      },
    );

    await act(async () => {
      await result.current.startTask(BRANCH);
    });

    expect(createTaskMock).toHaveBeenCalledWith(
      expect.objectContaining({
        taskDescription: BRANCH,
        repoPath: MAIN_REPO_PATH,
        workspaceMode: "worktree",
        branch: BRANCH,
        reuseExistingWorktree: true,
      }),
      expect.any(Function),
    );
    expect(invalidateTasksMock).toHaveBeenCalledWith(task);
    expect(openTaskMock).toHaveBeenCalledWith(task);
    expect(trackMock).toHaveBeenCalledWith(
      "Task created",
      expect.objectContaining({
        created_from: "sidebar-worktree",
        workspace_mode: "worktree",
      }),
    );
    expect(queryFilterMock).toHaveBeenCalledWith({
      mainRepoPath: MAIN_REPO_PATH,
    });
    expect(toastErrorMock).not.toHaveBeenCalled();
    expect(setFailedMock).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(result.current.startingBranches.has(BRANCH)).toBe(false),
    );
  });

  it("toasts and does not track when task creation fails validation", async () => {
    createTaskMock.mockResolvedValueOnce({
      success: false,
      error: "Task description cannot be empty",
      failedStep: "validation",
    });

    const { result } = renderHook(
      () => useStartTaskFromWorktree(MAIN_REPO_PATH),
      {
        wrapper,
      },
    );

    await act(async () => {
      await result.current.startTask(BRANCH);
    });

    expect(toastErrorMock).toHaveBeenCalledWith(
      "Task creation failed",
      "Task description cannot be empty",
    );
    expect(trackMock).not.toHaveBeenCalled();
    expect(invalidateTasksMock).not.toHaveBeenCalled();
    expect(queryFilterMock).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(result.current.startingBranches.has(BRANCH)).toBe(false),
    );
  });

  it("marks the task failed and toasts on a provisioning error, but still tracks and invalidates", async () => {
    const task = fakeTask();
    createTaskMock.mockImplementationOnce(async (_input, onTaskReady) => {
      const output = {
        task,
        workspace: null,
        provisioningError: "git clone failed",
      };
      onTaskReady?.(output);
      return { success: true, data: output };
    });

    const { result } = renderHook(
      () => useStartTaskFromWorktree(MAIN_REPO_PATH),
      {
        wrapper,
      },
    );

    await act(async () => {
      await result.current.startTask(BRANCH);
    });

    expect(setFailedMock).toHaveBeenCalledWith(task.id, "git clone failed");
    expect(toastErrorMock).toHaveBeenCalledWith(
      "Failed to create workspace",
      "git clone failed",
    );
    // Provisioning failure is still a successful task creation: the create
    // event still fires and the adoptable-worktrees list still refetches.
    expect(trackMock).toHaveBeenCalled();
    expect(queryFilterMock).toHaveBeenCalledWith({
      mainRepoPath: MAIN_REPO_PATH,
    });
    await waitFor(() =>
      expect(result.current.startingBranches.has(BRANCH)).toBe(false),
    );
  });

  it("toasts and clears the in-flight branch when createTask throws", async () => {
    createTaskMock.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(
      () => useStartTaskFromWorktree(MAIN_REPO_PATH),
      {
        wrapper,
      },
    );

    await act(async () => {
      await result.current.startTask(BRANCH);
    });

    expect(toastErrorMock).toHaveBeenCalledWith(
      "Failed to start task from worktree",
      expect.any(Error),
    );
    await waitFor(() =>
      expect(result.current.startingBranches.has(BRANCH)).toBe(false),
    );
  });
});
