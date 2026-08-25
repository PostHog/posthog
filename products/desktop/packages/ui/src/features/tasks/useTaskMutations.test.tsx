import type { Schemas } from "@posthog/api-client";
import type { Task } from "@posthog/shared/domain-types";
import {
  channelFeedQueryKey,
  channelFeedQueryRoot,
} from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import {
  type SpaceTaskPage,
  spaceTreeTasksQueryRoot,
} from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { taskFeedResultsQueryKey } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { act, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUpdateTask = vi.hoisted(() => vi.fn());
const mockHandoffTask = vi.hoisted(() => vi.fn());
const mockClient = vi.hoisted(() => ({
  updateTask: mockUpdateTask,
  handoffTask: mockHandoffTask,
}));
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
import { useHandoffTask, useRenameTask } from "./useTaskMutations";

const TASK_ID = "task-1";
const OTHER_TASK_ID = "task-2";
const SPACE_TREE_KEY = [...spaceTreeTasksQueryRoot, "space-1"] as const;

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

type TaskFeedResults = { tasks: Task[]; isComplete: boolean };

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
    const channelFeedKey = channelFeedQueryKey("channel-1");
    const taskFeedKey = taskFeedResultsQueryKey("created-by:@me");
    queryClient.setQueryData<Task[]>(listKey, [
      createTask(),
      createTask({ id: OTHER_TASK_ID, title: "Other" }),
    ]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
      createSummary({ id: OTHER_TASK_ID, title: "Other" }),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());
    queryClient.setQueryData<Task[]>(channelFeedKey, [createTask()]);
    queryClient.setQueryData<SpaceTaskPage>(SPACE_TREE_KEY, {
      tasks: [createTask()],
      count: 7,
    });
    queryClient.setQueryData<TaskFeedResults>(taskFeedKey, {
      tasks: [createTask()],
      isComplete: true,
    });

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
    expect(queryClient.getQueryData<Task[]>(channelFeedKey)?.[0]).toMatchObject(
      {
        title: "Renamed",
        title_manually_set: true,
      },
    );
    expect(
      queryClient.getQueryData<SpaceTaskPage>(SPACE_TREE_KEY),
    ).toMatchObject({
      tasks: [{ title: "Renamed", title_manually_set: true }],
      count: 7,
    });
    expect(
      queryClient.getQueryData<TaskFeedResults>(taskFeedKey)?.tasks[0],
    ).toMatchObject({
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
    const channelFeedKey = channelFeedQueryKey("channel-1");
    const taskFeedKey = taskFeedResultsQueryKey("created-by:@me");
    queryClient.setQueryData<Task[]>(listKey, [createTask()]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());
    queryClient.setQueryData<Task[]>(channelFeedKey, [createTask()]);
    queryClient.setQueryData<SpaceTaskPage>(SPACE_TREE_KEY, {
      tasks: [createTask()],
      count: 7,
    });
    queryClient.setQueryData<TaskFeedResults>(taskFeedKey, {
      tasks: [createTask()],
      isComplete: true,
    });

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
    expect(queryClient.getQueryData<Task[]>(channelFeedKey)?.[0].title).toBe(
      "Original title",
    );
    expect(
      queryClient.getQueryData<SpaceTaskPage>(SPACE_TREE_KEY)?.tasks[0].title,
    ).toBe("Original title");
    expect(
      queryClient.getQueryData<TaskFeedResults>(taskFeedKey)?.tasks[0].title,
    ).toBe("Original title");

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
    let failUpdate: (() => void) | undefined;
    mockUpdateTask.mockReturnValue(
      new Promise((_, reject) => {
        failUpdate = () => reject(failure);
      }),
    );
    const { result, queryClient } = renderRenameHook();

    const listKey = taskKeys.list();
    const summaryKey = taskKeys.summaries([TASK_ID]);
    const detailKey = taskKeys.detail(TASK_ID);
    queryClient.setQueryData<Task[]>(listKey, [createTask()]);
    queryClient.setQueryData<Schemas.TaskSummary[]>(summaryKey, [
      createSummary(),
    ]);
    queryClient.setQueryData<Task>(detailKey, createTask());
    queryClient.setQueryData<SpaceTaskPage>(SPACE_TREE_KEY, {
      tasks: [createTask()],
      count: 7,
    });

    const renamePromise = result.current.renameTask({
      taskId: TASK_ID,
      currentTitle: "Original title",
      newTitle: "First rename",
    });

    // Our own optimistic write has to land before the newer rename overtakes
    // it, or the test states the opposite of what it names.
    await waitFor(() => {
      expect(queryClient.getQueryData<Task[]>(listKey)?.[0].title).toBe(
        "First rename",
      );
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
    queryClient.setQueryData<SpaceTaskPage>(SPACE_TREE_KEY, {
      tasks: [createTask({ title: "Second rename", title_manually_set: true })],
      count: 7,
    });

    let caught: unknown;
    await act(async () => {
      failUpdate?.();
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
    expect(
      queryClient.getQueryData<SpaceTaskPage>(SPACE_TREE_KEY)?.tasks[0].title,
    ).toBe("Second rename");

    expect(mockUpdateSessionTaskTitle).not.toHaveBeenCalledWith(
      TASK_ID,
      "Original title",
    );
  });

  it("keeps the new title when a poll that was already in flight resolves with the old one", async () => {
    mockUpdateTask.mockResolvedValue(undefined);
    const { result, queryClient } = renderRenameHook();

    queryClient.setQueryData<SpaceTaskPage>(SPACE_TREE_KEY, {
      tasks: [createTask()],
      count: 7,
    });
    let resolvePoll: ((page: SpaceTaskPage) => void) | undefined;
    const inFlightPoll = queryClient
      .fetchQuery<SpaceTaskPage>({
        queryKey: SPACE_TREE_KEY,
        queryFn: () =>
          new Promise<SpaceTaskPage>((resolve) => {
            resolvePoll = resolve;
          }),
      })
      .catch(() => undefined);

    await act(async () => {
      await result.current.renameTask({
        taskId: TASK_ID,
        currentTitle: "Original title",
        newTitle: "Renamed",
      });
    });

    await act(async () => {
      resolvePoll?.({ tasks: [createTask()], count: 7 });
      await inFlightPoll;
    });

    expect(
      queryClient.getQueryData<SpaceTaskPage>(SPACE_TREE_KEY)?.tasks[0].title,
    ).toBe("Renamed");
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

describe("useHandoffTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("forwards the recipient id and invalidates the views a handoff redraws", async () => {
    mockHandoffTask.mockResolvedValue(createTask({ created_by: null }));
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useHandoffTask(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ taskId: TASK_ID, userId: 7 });
    });

    expect(mockHandoffTask).toHaveBeenCalledWith(TASK_ID, 7);
    // Skipping these would leave the old owner staring at a task (and a channel)
    // the backend already moved to the recipient's space.
    const invalidatedKeys = invalidateSpy.mock.calls.map(
      ([options]) => options?.queryKey,
    );
    expect(invalidatedKeys).toContainEqual(taskKeys.lists());
    expect(invalidatedKeys).toContainEqual(taskKeys.detail(TASK_ID));
    expect(invalidatedKeys).toContainEqual(TASK_CHANNELS_QUERY_KEY);
    expect(invalidatedKeys).toContainEqual(channelFeedQueryRoot);
  });
});
