import type { Task } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRefreshedTask } from "./useRefreshedTask";

const mocks = vi.hoisted(() => ({ getTask: vi.fn() }));

vi.mock("@posthog/ui/features/auth/authClientImperative", () => ({
  getAuthenticatedClient: vi.fn(async () => ({ getTask: mocks.getTask })),
}));

function task(runId: string, status: "failed" | "in_progress"): Task {
  return {
    id: "task-123",
    title: "Cloud task",
    description: "Keep working",
    repository: null,
    latest_run: {
      id: runId,
      task: "task-123",
      environment: "cloud",
      status,
      state: {},
    },
  } as Task;
}

describe("useRefreshedTask", () => {
  beforeEach(() => {
    mocks.getTask.mockReset();
  });

  it("replaces a cached failed run with the authoritative resumed run", async () => {
    const failedParent = task("run-parent", "failed");
    const resumedChild = task("run-child", "in_progress");
    mocks.getTask.mockResolvedValue(resumedChild);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () => useRefreshedTask("task-123", failedParent),
      { wrapper },
    );

    expect(result.current.latest_run?.id).toBe("run-parent");
    await waitFor(() => {
      expect(result.current.latest_run?.id).toBe("run-child");
    });
    expect(mocks.getTask).toHaveBeenCalledWith("task-123");
  });
});
