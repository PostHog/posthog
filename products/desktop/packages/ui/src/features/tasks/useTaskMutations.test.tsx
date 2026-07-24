import type { Schemas } from "@posthog/api-client";
import type { Task } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { act, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUpdateTask = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({ updateTask: mockUpdateTask }));
const mockUpdateSessionTaskTitle = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    updateSessionTaskTitle: mockUpdateSessionTaskTitle,
  }),
}));

import { taskKeys } from "./taskKeys";
import { useRenameTask } from "./useTaskMutations";

const TASK_ID = "task-1";
const OTHER_TASK_ID = "task-2";

function createTask(overrides: Partial<Task> = {}): Task {
  return {
    id: TASK_ID,
    task_number: 1,
    slug: "task-1",
    title: "Original title",
    description: "Original description",
    created_at: "2026-05-28T00:00:00.000Z",
    updated_at: "2026-05-28T00:00:00.000Z",
    origin_product: "user_created",
    ...overrides,
  };
}

function createSummary(overrides: Partial<Schemas.TaskSummary> = {}) {
  return {
    id: TASK_ID,
    title: "Original title",
    ...overrides,
  } as Schemas.TaskSummary;
}

function renderRenameHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const result = renderHook(() => useRenameTask(), { wrapper });
  return { ...result, queryClient };
}

describe("useRenameTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("applies the new title optimistically to list, summaries, and detail caches", async () => {
    mockUpdateTask.mockResolvedValue(undefined);
    const { result, queryClient } = renderRenameHook();

    const listKey = taskKeys.list();
    const summaryKey = taskKeys.summaries([TASK_ID]);
    const detailKey = taskKeys.detail(TASK_ID);
    queryClient.setQueryData<Task[]>(listKey, [
      createTask(),
      createTask({ id: OTHER_TASK_ID, title: "Other" }),
    ]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
      createSummary({ id: OTHER_TASK_ID, title: "Other" }),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());

    await act(async () => {
      await result.current.renameTask({
        taskId: TASK_ID,
        currentTitle: "Original title",
        newTitle: "Renamed",
      });
    });

    const list = queryClient.getQueryData<Task[]>(listKey);
    expect(list?.find((t) => t.id === TASK_ID)).toMatchObject({
      title: "Renamed",
      title_manually_set: true,
    });
    expect(list?.find((t) => t.id === OTHER_TASK_ID)).toMatchObject({
      title: "Other",
    });

    const summaries =
      queryClient.getQueryData<Schemas.TaskSummary[]>(summaryKey);
    expect(summaries?.find((t) => t.id === TASK_ID)?.title).toBe("Renamed");
    expect(summaries?.find((t) => t.id === OTHER_TASK_ID)?.title).toBe("Other");

    const detail = queryClient.getQueryData<Task>(detailKey);
    expect(detail).toMatchObject({
      title: "Renamed",
      title_manually_set: true,
    });

    expect(mockUpdateTask).toHaveBeenCalledWith(TASK_ID, {
      title: "Renamed",
      title_manually_set: true,
    });
    expect(mockUpdateSessionTaskTitle).toHaveBeenCalledWith(TASK_ID, "Renamed");
  });

  it("rolls back all caches and notifies the session service with the original title on failure", async () => {
    const failure = new Error("network down");
    mockUpdateTask.mockRejectedValue(failure);
    const { result, queryClient } = renderRenameHook();

    const listKey = taskKeys.list();
    const summaryKey = taskKeys.summaries([TASK_ID]);
    const detailKey = taskKeys.detail(TASK_ID);
    queryClient.setQueryData<Task[]>(listKey, [createTask()]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.renameTask({
          taskId: TASK_ID,
          currentTitle: "Original title",
          newTitle: "Renamed",
        });
      } catch (error) {
        caught = error;
      }
    });
    expect(caught).toBe(failure);

    expect(queryClient.getQueryData<Task[]>(listKey)?.[0].title).toBe(
      "Original title",
    );
    expect(
      queryClient.getQueryData<Task[]>(listKey)?.[0].title_manually_set,
    ).toBeUndefined();
    expect(
      queryClient.getQueryData<Schemas.TaskSummary[]>(summaryKey)?.[0].title,
    ).toBe("Original title");
    expect(queryClient.getQueryData<Task>(detailKey)?.title).toBe(
      "Original title",
    );

    expect(mockUpdateSessionTaskTitle).toHaveBeenNthCalledWith(
      1,
      TASK_ID,
      "Renamed",
    );
    expect(mockUpdateSessionTaskTitle).toHaveBeenNthCalledWith(
      2,
      TASK_ID,
      "Original title",
    );
  });

  it("skips rollback when a newer rename has advanced the title past ours", async () => {
    const failure = new Error("network down");
    mockUpdateTask.mockRejectedValue(failure);
    const { result, queryClient } = renderRenameHook();

    const listKey = taskKeys.list();
    const summaryKey = taskKeys.summaries([TASK_ID]);
    const detailKey = taskKeys.detail(TASK_ID);
    queryClient.setQueryData<Task[]>(listKey, [createTask()]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());

    const renamePromise = result.current.renameTask({
      taskId: TASK_ID,
      currentTitle: "Original title",
      newTitle: "First rename",
    });

    queryClient.setQueryData<Task[]>(listKey, [
      createTask({ title: "Second rename", title_manually_set: true }),
    ]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary({ title: "Second rename" }),
    ]);
    queryClient.setQueryData<Task>(
      detailKey,
      createTask({ title: "Second rename", title_manually_set: true }),
    );

    let caught: unknown;
    await act(async () => {
      try {
        await renamePromise;
      } catch (error) {
        caught = error;
      }
    });
    expect(caught).toBe(failure);

    expect(queryClient.getQueryData<Task[]>(listKey)?.[0].title).toBe(
      "Second rename",
    );
    expect(
      queryClient.getQueryData<Schemas.TaskSummary[]>(summaryKey)?.[0].title,
    ).toBe("Second rename");
    expect(queryClient.getQueryData<Task>(detailKey)?.title).toBe(
      "Second rename",
    );

    expect(mockUpdateSessionTaskTitle).not.toHaveBeenCalledWith(
      TASK_ID,
      "Original title",
    );
  });

  it("does not write to the detail cache when no detail entry exists", async () => {
    mockUpdateTask.mockResolvedValue(undefined);
    const { result, queryClient } = renderRenameHook();

    queryClient.setQueryData<Task[]>(taskKeys.list(), [createTask()]);

    await act(async () => {
      await result.current.renameTask({
        taskId: TASK_ID,
        currentTitle: "Original title",
        newTitle: "Renamed",
      });
    });

    expect(queryClient.getQueryData(taskKeys.detail(TASK_ID))).toBeUndefined();
    expect(queryClient.getQueryData<Task[]>(taskKeys.list())?.[0].title).toBe(
      "Renamed",
    );
  });
});
