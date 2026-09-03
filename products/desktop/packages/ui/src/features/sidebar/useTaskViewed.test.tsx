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
    },
  }),
}));

import { useTaskViewed } from "./useTaskViewed";

describe("useTaskViewed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.markViewed.mockResolvedValue(undefined);
  });

  it("clears unread through the task activity timestamp", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const activityAt = new Date(Date.now() + 60_000).toISOString();
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

    act(() => result.current.markAsViewed("task-1", activityAt));

    await waitFor(() => {
      expect(
        isTaskUnread(activityAt, result.current.timestamps["task-1"]),
      ).toBe(false);
    });
    expect(mocks.markViewed).toHaveBeenCalledWith({
      taskId: "task-1",
      activityAt,
    });
  });
});
