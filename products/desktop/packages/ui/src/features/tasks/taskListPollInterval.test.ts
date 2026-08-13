import { describe, expect, it } from "vitest";
import {
  TASK_LIST_FALLBACK_POLL_INTERVAL_MS,
  TASK_LIST_POLL_INTERVAL_MS,
  type TaskListHookFilters,
  taskListRefetchIntervalMs,
} from "./taskListPollInterval";

describe("taskListRefetchIntervalMs", () => {
  it.each<{
    name: string;
    filters: TaskListHookFilters | undefined;
    allUsersListMounted: boolean;
    expected: number;
  }>([
    {
      name: "plain mine list falls back while an all-users list is mounted",
      filters: undefined,
      allUsersListMounted: true,
      expected: TASK_LIST_FALLBACK_POLL_INTERVAL_MS,
    },
    {
      name: "plain mine list keeps full cadence without an all-users list",
      filters: undefined,
      allUsersListMounted: false,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "all-users list keeps full cadence (it is the covering poll itself)",
      filters: { showAllUsers: true },
      allUsersListMounted: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "repository-filtered list keeps full cadence",
      filters: { repository: "posthog/example" },
      allUsersListMounted: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "internal list keeps full cadence",
      filters: { showInternal: true },
      allUsersListMounted: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
  ])("$name", ({ filters, allUsersListMounted, expected }) => {
    expect(taskListRefetchIntervalMs(filters, allUsersListMounted)).toBe(
      expected,
    );
  });
});
