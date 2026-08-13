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
    channelsWorldActive: boolean;
    expected: number;
  }>([
    {
      name: "plain mine list falls back while the channels world polls org-wide",
      filters: undefined,
      channelsWorldActive: true,
      expected: TASK_LIST_FALLBACK_POLL_INTERVAL_MS,
    },
    {
      name: "plain mine list keeps full cadence without the channels world",
      filters: undefined,
      channelsWorldActive: false,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "all-users list keeps full cadence (it is the badge poll itself)",
      filters: { showAllUsers: true },
      channelsWorldActive: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "repository-filtered list keeps full cadence",
      filters: { repository: "posthog/example" },
      channelsWorldActive: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
    {
      name: "internal list keeps full cadence",
      filters: { showInternal: true },
      channelsWorldActive: true,
      expected: TASK_LIST_POLL_INTERVAL_MS,
    },
  ])("$name", ({ filters, channelsWorldActive, expected }) => {
    expect(taskListRefetchIntervalMs(filters, channelsWorldActive)).toBe(
      expected,
    );
  });
});
