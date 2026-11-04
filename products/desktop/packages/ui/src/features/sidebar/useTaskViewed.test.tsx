import { isTaskUnread } from "@posthog/core/sidebar/buildSidebarData";
import type { RawTaskTimestamp } from "@posthog/core/sidebar/taskMeta";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const TIMESTAMPS_QUERY_KEY = ["task-timestamps"];
const mocks = vi.hoisted(() => ({
  loadTimestamps: vi.fn(),
  markActivity: vi.fn(),
  markViewed: vi.fn(),
  markUnread: vi.fn(),
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
      markViewed: { mutate: mocks.markViewed },
      markUnread: { mutate: mocks.markUnread },
    },
  }),
}));

import { useTaskViewed } from "./useTaskViewed";

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

describe("useTaskViewed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.markViewed.mockResolvedValue(undefined);
  });

  it("clears unread immediately when a task is viewed", async () => {
    const { queryClient, wrapper } = setup();
    const activityAt = new Date(Date.now() - 60_000).toISOString();
    queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
      TIMESTAMPS_QUERY_KEY,
      {
        "task-1": {
          pinnedAt: null,
          lastViewedAt: "2026-01-01T00:00:00.000Z",
          lastActivityAt: null,
        },
      },
    );
    const { result } = renderHook(() => useTaskViewed(), { wrapper });

    act(() => result.current.markAsViewed("task-1"));

    await waitFor(() => {
      expect(
        isTaskUnread(activityAt, result.current.timestamps["task-1"]),
      ).toBe(false);
    });
    expect(mocks.markViewed).toHaveBeenCalledWith({
      taskId: "task-1",
    });
  });

  it("rolls back a failed unread without losing a view that landed meanwhile", async () => {
    const { queryClient, wrapper } = setup();
    const viewedAt = "2026-01-01T00:00:00.000Z";
    queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
      TIMESTAMPS_QUERY_KEY,
      {
        "task-1": {
          pinnedAt: null,
          lastViewedAt: viewedAt,
          lastActivityAt: null,
        },
        "task-2": { pinnedAt: null, lastViewedAt: null, lastActivityAt: null },
      },
    );
    let failUnread: (error: Error) => void = () => undefined;
    mocks.markUnread.mockReturnValue(
      new Promise((_, reject) => {
        failUnread = reject;
      }),
    );
    const { result } = renderHook(() => useTaskViewed(), { wrapper });

    act(() =>
      result.current.markAsUnread(
        "task-1",
        new Date(viewedAt).getTime() + 60_000,
      ),
    );
    await waitFor(() =>
      expect(result.current.timestamps["task-1"]?.lastViewedAt).not.toBe(
        new Date(viewedAt).getTime(),
      ),
    );
    act(() => result.current.markAsViewed("task-2"));
    await waitFor(() =>
      expect(result.current.timestamps["task-2"]?.lastViewedAt).not.toBeNull(),
    );
    await act(async () => failUnread(new Error("host unavailable")));

    await waitFor(() =>
      expect(result.current.timestamps["task-1"]?.lastViewedAt).toBe(
        new Date(viewedAt).getTime(),
      ),
    );
    expect(result.current.timestamps["task-2"]?.lastViewedAt).not.toBeNull();
  });
});
