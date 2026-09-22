import type { Task } from "@posthog/shared/domain-types";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getAuthenticatedClient: vi.fn(),
  getTask: vi.fn(),
  navigateToTaskDetail: vi.fn(),
  openTask: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClientImperative", () => ({
  getAuthenticatedClient: mocks.getAuthenticatedClient,
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToTaskDetail: mocks.navigateToTaskDetail,
}));

vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask: mocks.openTask,
}));

import { openSidebarTask, resolveSidebarTask } from "./sidebarTaskInteractions";

const task = {
  id: "task-1",
  title: "Investigate slow startup",
  created_at: "2026-09-02T09:00:00Z",
  updated_at: "2026-09-02T09:00:00Z",
} as Task;

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { gcTime: Infinity, retry: false } },
  });
}

describe("sidebar task interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAuthenticatedClient.mockResolvedValue({ getTask: mocks.getTask });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens a cold task through the full task workflow", async () => {
    mocks.getTask.mockResolvedValue(task);

    await openSidebarTask(createQueryClient(), task.id);

    expect(mocks.openTask).toHaveBeenCalledWith(task);
    expect(mocks.navigateToTaskDetail).not.toHaveBeenCalled();
  });

  it("resolves the full task for a deferred menu action", async () => {
    mocks.getTask.mockResolvedValue(task);

    await expect(
      resolveSidebarTask(createQueryClient(), task.id),
    ).resolves.toBe(task);
  });

  it("does not drop a deferred menu action when task loading is slow", async () => {
    vi.useFakeTimers();
    let resolveTask: (value: Task) => void = () => undefined;
    mocks.getTask.mockReturnValue(
      new Promise<Task>((resolve) => {
        resolveTask = resolve;
      }),
    );
    const result = resolveSidebarTask(createQueryClient(), task.id);

    await vi.advanceTimersByTimeAsync(5_000);

    resolveTask(task);
    await expect(result).resolves.toBe(task);
  });
});
