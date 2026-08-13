import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUseAuthenticatedQuery = vi.hoisted(() =>
  vi.fn((..._args: unknown[]) => ({ data: [] })),
);
vi.mock("../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: mockUseAuthenticatedQuery,
}));
vi.mock("../auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: { id: 1 } }),
}));

import { useAllUsersTaskPollStore } from "./allUsersTaskPollStore";
import {
  TASK_LIST_FALLBACK_POLL_INTERVAL_MS,
  TASK_LIST_POLL_INTERVAL_MS,
} from "./taskListPollInterval";
import { useTasks } from "./useTasks";

function latestMineInterval(): number | undefined {
  const calls = mockUseAuthenticatedQuery.mock.calls.filter((call) => {
    const key = call[0] as unknown[];
    const filters = key[key.length - 1] as { createdBy?: number } | undefined;
    return filters?.createdBy === 1;
  });
  const options = calls.at(-1)?.[2] as { refetchInterval?: number } | undefined;
  return options?.refetchInterval;
}

describe("useTasks", () => {
  beforeEach(() => {
    mockUseAuthenticatedQuery.mockClear();
    useAllUsersTaskPollStore.setState({ observers: 0 });
  });

  it("demotes the plain mine poll only while an all-users list is mounted", () => {
    const mine = renderHook(() => useTasks());
    expect(latestMineInterval()).toBe(TASK_LIST_POLL_INTERVAL_MS);

    const allUsers = renderHook(() => useTasks({ showAllUsers: true }));
    expect(latestMineInterval()).toBe(TASK_LIST_FALLBACK_POLL_INTERVAL_MS);

    allUsers.unmount();
    expect(latestMineInterval()).toBe(TASK_LIST_POLL_INTERVAL_MS);

    mine.unmount();
  });

  it("ignores a disabled all-users list", () => {
    const mine = renderHook(() => useTasks());
    const allUsers = renderHook(() =>
      useTasks({ showAllUsers: true }, { enabled: false }),
    );

    expect(latestMineInterval()).toBe(TASK_LIST_POLL_INTERVAL_MS);

    allUsers.unmount();
    mine.unmount();
  });
});
