import { isTaskUnread } from "@posthog/core/sidebar/buildSidebarData";
import type { RawTaskTimestamp } from "@posthog/core/sidebar/taskMeta";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TIMESTAMPS_QUERY_KEY = ["task-timestamps"];
const NOW_MS = Date.parse("2026-01-01T00:10:00.000Z");
const mocks = vi.hoisted(() => ({
  loadTimestamps: vi.fn(),
  markActivity: vi.fn(),
  markUnread: vi.fn(),
  markViewed: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    workspace: {
      getAllTaskTimestamps: {
        queryKey: () => TIMESTAMPS_QUERY_KEY,
        queryOptions: (
          _input: undefined,
          options: Record<string, unknown>,
        ) => ({
          queryKey: TIMESTAMPS_QUERY_KEY,
          queryFn: mocks.loadTimestamps,
          ...options,
        }),
      },
    },
  }),
  useHostTRPCClient: () => ({
    workspace: {
      markActivity: { mutate: mocks.markActivity },
      markUnread: { mutate: mocks.markUnread },
      markViewed: { mutate: mocks.markViewed },
    },
  }),
}));

import { useTaskViewed } from "./useTaskViewed";

function createDeferred<Result = void>() {
  let resolve!: (value: Result | PromiseLike<Result>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<Result>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createHarness(initialTimestamps: Record<string, RawTaskTimestamp>) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(TIMESTAMPS_QUERY_KEY, initialTimestamps);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useTaskViewed(), { wrapper });
  return { queryClient, wrapper, ...hook };
}

function cachedTimestamps(
  queryClient: QueryClient,
): Record<string, RawTaskTimestamp> | undefined {
  return queryClient.getQueryData(TIMESTAMPS_QUERY_KEY);
}

describe("useTaskViewed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Date, "now").mockReturnValue(NOW_MS);
    mocks.loadTimestamps.mockResolvedValue({});
    mocks.markActivity.mockResolvedValue(undefined);
    mocks.markUnread.mockResolvedValue(undefined);
    mocks.markViewed.mockResolvedValue(undefined);
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows unread immediately and keeps the final cache after success", async () => {
    const request = createDeferred();
    mocks.markUnread.mockReturnValue(request.promise);
    const activityAt = "2026-01-01T00:01:00.000Z";
    const initialTask = {
      pinnedAt: null,
      lastViewedAt: "2026-01-01T00:02:00.000Z",
      lastActivityAt: null,
    };
    const { queryClient, result } = createHarness({ "task-1": initialTask });

    act(() => result.current.markAsUnread("task-1", Date.parse(activityAt)));

    await waitFor(() => {
      expect(
        isTaskUnread(activityAt, result.current.timestamps["task-1"]),
      ).toBe(true);
    });
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      ...initialTask,
      lastViewedAt: "2026-01-01T00:00:59.999Z",
    });

    request.resolve();
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      ...initialTask,
      lastViewedAt: "2026-01-01T00:00:59.999Z",
    });
  });

  it("uses supplied activity to clear unread despite device clock skew", async () => {
    const activityAtMs = Date.parse("2026-01-01T00:20:00.000Z");
    const storedActivityAt = "2026-01-01T00:30:00.000Z";
    const { queryClient, result } = createHarness({
      "task-1": {
        pinnedAt: null,
        lastViewedAt: "2026-01-01T00:00:00.000Z",
        lastActivityAt: storedActivityAt,
      },
    });

    act(() => result.current.markAsViewed("task-1", activityAtMs));

    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());
    expect(mocks.markViewed).toHaveBeenCalledWith({
      taskId: "task-1",
      activityAtMs,
    });
    expect(cachedTimestamps(queryClient)?.["task-1"]?.lastViewedAt).toBe(
      storedActivityAt,
    );
  });

  it("orders each task independently while applying every optimistic update immediately", async () => {
    const firstTaskViewed = createDeferred();
    const secondTaskViewed = createDeferred();
    const firstTaskUnread = createDeferred();
    mocks.markViewed.mockImplementation(({ taskId }: { taskId: string }) =>
      taskId === "task-1" ? firstTaskViewed.promise : secondTaskViewed.promise,
    );
    mocks.markUnread.mockReturnValue(firstTaskUnread.promise);
    const taskTwoInitial = {
      pinnedAt: "2025-12-01T00:00:00.000Z",
      lastViewedAt: null,
      lastActivityAt: null,
    };
    const { queryClient, result } = createHarness({
      "task-1": {
        pinnedAt: null,
        lastViewedAt: null,
        lastActivityAt: "2026-01-01T00:01:00.000Z",
      },
      "task-2": taskTwoInitial,
    });

    act(() => {
      result.current.markAsViewed("task-1");
      result.current.markAsUnread("task-1", Date.parse("2026-01-01T00:02:00Z"));
      result.current.markActivity("task-1");
      result.current.markAsViewed("task-2");
    });

    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledTimes(2));
    expect(mocks.markUnread).not.toHaveBeenCalled();
    expect(mocks.markActivity).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
        pinnedAt: null,
        lastViewedAt: "2026-01-01T00:01:59.999Z",
        lastActivityAt: new Date(NOW_MS).toISOString(),
      });
      expect(cachedTimestamps(queryClient)?.["task-2"]).toEqual({
        ...taskTwoInitial,
        lastViewedAt: new Date(NOW_MS).toISOString(),
      });
    });

    secondTaskViewed.resolve();
    firstTaskViewed.resolve();
    await waitFor(() => expect(mocks.markUnread).toHaveBeenCalledOnce());
    expect(mocks.markActivity).not.toHaveBeenCalled();

    firstTaskUnread.resolve();
    await waitFor(() => expect(mocks.markActivity).toHaveBeenCalledOnce());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      pinnedAt: null,
      lastViewedAt: "2026-01-01T00:01:59.999Z",
      lastActivityAt: new Date(NOW_MS).toISOString(),
    });
    expect(cachedTimestamps(queryClient)?.["task-2"]).toEqual({
      ...taskTwoInitial,
      lastViewedAt: new Date(NOW_MS).toISOString(),
    });
  });

  it("orders requests across hook instances before reconciling an older failure", async () => {
    const firstViewedRequest = createDeferred();
    const secondViewedRequest = createDeferred();
    mocks.markViewed
      .mockReturnValueOnce(firstViewedRequest.promise)
      .mockReturnValueOnce(secondViewedRequest.promise);
    const initialTask = {
      pinnedAt: null,
      lastViewedAt: "2026-01-01T00:00:00.000Z",
      lastActivityAt: null,
    };
    const persistedTimestamps = {
      "task-1": {
        ...initialTask,
        lastViewedAt: new Date(NOW_MS).toISOString(),
      },
    };
    mocks.loadTimestamps.mockResolvedValue(persistedTimestamps);
    const { queryClient, result, wrapper } = createHarness({
      "task-1": initialTask,
    });
    const secondHook = renderHook(() => useTaskViewed(), { wrapper });

    act(() => {
      result.current.markAsViewed("task-1");
      secondHook.result.current.markAsViewed("task-1");
    });

    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());
    expect(cachedTimestamps(queryClient)?.["task-1"]?.lastViewedAt).toBe(
      new Date(NOW_MS).toISOString(),
    );

    firstViewedRequest.reject(new Error("first view failed"));
    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledTimes(2));
    expect(mocks.loadTimestamps).not.toHaveBeenCalled();
    expect(cachedTimestamps(queryClient)?.["task-1"]?.lastViewedAt).toBe(
      new Date(NOW_MS).toISOString(),
    );

    secondViewedRequest.resolve();
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)).toEqual(persistedTimestamps);
  });

  it("waits for a newer optimistic action before reconciling an older failure", async () => {
    const viewedRequest = createDeferred();
    const unreadRequest = createDeferred();
    mocks.markViewed.mockReturnValue(viewedRequest.promise);
    mocks.markUnread.mockReturnValue(unreadRequest.promise);
    const otherTask = {
      pinnedAt: null,
      lastViewedAt: "2025-12-01T00:00:00.000Z",
      lastActivityAt: null,
    };
    const initialTask = {
      pinnedAt: null,
      lastViewedAt: "2026-01-01T00:00:00.000Z",
      lastActivityAt: "2026-01-01T00:02:00.000Z",
    };
    const persistedTimestamps = {
      "task-1": {
        ...initialTask,
        lastViewedAt: "2026-01-01T00:01:59.999Z",
      },
      "task-2": otherTask,
    };
    mocks.loadTimestamps.mockResolvedValue(persistedTimestamps);
    const { queryClient, result } = createHarness({
      "task-1": initialTask,
      "task-2": otherTask,
    });

    act(() => {
      result.current.markAsViewed(
        "task-1",
        Date.parse("2026-01-01T00:03:00.000Z"),
      );
      result.current.markAsUnread(
        "task-1",
        Date.parse("2026-01-01T00:02:00.000Z"),
      );
    });
    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());

    viewedRequest.reject(new Error("view failed"));
    await waitFor(() => expect(mocks.markUnread).toHaveBeenCalledOnce());
    expect(cachedTimestamps(queryClient)?.["task-1"]?.lastViewedAt).toBe(
      "2026-01-01T00:01:59.999Z",
    );
    expect(cachedTimestamps(queryClient)?.["task-2"]).toEqual(otherTask);

    unreadRequest.resolve();
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)).toEqual(persistedTimestamps);
  });

  it("keeps newer activity optimistic until the failed queue reconciles", async () => {
    const viewedRequest = createDeferred();
    const activityRequest = createDeferred();
    mocks.markViewed.mockReturnValue(viewedRequest.promise);
    mocks.markActivity.mockReturnValue(activityRequest.promise);
    const initialTask = {
      pinnedAt: null,
      lastViewedAt: "2026-01-01T00:00:00.000Z",
      lastActivityAt: "2026-01-01T00:01:00.000Z",
    };
    const persistedTimestamps = {
      "task-1": {
        ...initialTask,
        lastActivityAt: new Date(NOW_MS + 1).toISOString(),
      },
    };
    mocks.loadTimestamps.mockResolvedValue(persistedTimestamps);
    const { queryClient, result } = createHarness({ "task-1": initialTask });

    act(() => {
      result.current.markAsViewed("task-1");
      result.current.markActivity("task-1");
    });
    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());

    viewedRequest.reject(new Error("view failed"));
    await waitFor(() => expect(mocks.markActivity).toHaveBeenCalledOnce());
    const optimisticActivityAt = new Date(NOW_MS + 1).toISOString();
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      ...initialTask,
      lastViewedAt: new Date(NOW_MS).toISOString(),
      lastActivityAt: optimisticActivityAt,
    });

    activityRequest.resolve();
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)).toEqual(persistedTimestamps);
  });

  it("cancels a reconciliation read before a newer optimistic mutation", async () => {
    const viewedRequest = createDeferred();
    const activityRequest = createDeferred();
    const reconciliationRead =
      createDeferred<Record<string, RawTaskTimestamp>>();
    let reconciliationSignal: AbortSignal | undefined;
    mocks.markViewed.mockReturnValue(viewedRequest.promise);
    mocks.markActivity.mockReturnValue(activityRequest.promise);
    mocks.loadTimestamps.mockImplementation(
      ({ signal }: { signal: AbortSignal }) => {
        reconciliationSignal = signal;
        return reconciliationRead.promise;
      },
    );
    const persistedTimestamps = {
      "task-1": {
        pinnedAt: null,
        lastViewedAt: "2026-01-01T00:00:00.000Z",
        lastActivityAt: null,
      },
    };
    const { queryClient, result } = createHarness(persistedTimestamps);

    act(() => result.current.markAsViewed("task-1"));
    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());
    viewedRequest.reject(new Error("view failed"));
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    expect(reconciliationSignal?.aborted).toBe(false);

    act(() => result.current.markActivity("task-1"));
    await waitFor(() => expect(mocks.markActivity).toHaveBeenCalledOnce());
    expect(reconciliationSignal?.aborted).toBe(true);
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      ...persistedTimestamps["task-1"],
      lastViewedAt: new Date(NOW_MS).toISOString(),
      lastActivityAt: new Date(NOW_MS + 1).toISOString(),
    });

    reconciliationRead.resolve(persistedTimestamps);
    activityRequest.resolve();
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)?.["task-1"]).toEqual({
      ...persistedTimestamps["task-1"],
      lastViewedAt: new Date(NOW_MS).toISOString(),
      lastActivityAt: new Date(NOW_MS + 1).toISOString(),
    });
  });

  it("removes only a failed optimistic task that had no prior cache row", async () => {
    const request = createDeferred();
    mocks.markActivity.mockReturnValue(request.promise);
    const otherTask = {
      pinnedAt: null,
      lastViewedAt: null,
      lastActivityAt: "2026-01-01T00:00:00.000Z",
    };
    const persistedTimestamps = { "task-2": otherTask };
    mocks.loadTimestamps.mockResolvedValue(persistedTimestamps);
    const { queryClient, result } = createHarness(persistedTimestamps);

    act(() => result.current.markActivity("task-1"));
    await waitFor(() => expect(mocks.markActivity).toHaveBeenCalledOnce());
    expect(cachedTimestamps(queryClient)?.["task-1"]).toBeDefined();

    request.reject(new Error("activity failed"));
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)).toEqual(persistedTimestamps);
  });

  it("returns to committed state after consecutive same-field failures", async () => {
    const firstViewedRequest = createDeferred();
    const secondViewedRequest = createDeferred();
    mocks.markViewed
      .mockReturnValueOnce(firstViewedRequest.promise)
      .mockReturnValueOnce(secondViewedRequest.promise);
    const persistedTimestamps = {
      "task-1": {
        pinnedAt: null,
        lastViewedAt: "2026-01-01T00:00:00.000Z",
        lastActivityAt: "2026-01-01T00:01:00.000Z",
      },
    };
    mocks.loadTimestamps.mockResolvedValue(persistedTimestamps);
    const { queryClient, result } = createHarness(persistedTimestamps);

    act(() => {
      result.current.markAsViewed("task-1");
      result.current.markAsViewed("task-1");
    });

    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledOnce());
    expect(cachedTimestamps(queryClient)?.["task-1"]?.lastViewedAt).toBe(
      new Date(NOW_MS).toISOString(),
    );

    firstViewedRequest.reject(new Error("first view failed"));
    await waitFor(() => expect(mocks.markViewed).toHaveBeenCalledTimes(2));
    expect(mocks.loadTimestamps).not.toHaveBeenCalled();

    secondViewedRequest.reject(new Error("second view failed"));
    await waitFor(() => expect(mocks.loadTimestamps).toHaveBeenCalled());
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(cachedTimestamps(queryClient)).toEqual(persistedTimestamps);
  });
});
