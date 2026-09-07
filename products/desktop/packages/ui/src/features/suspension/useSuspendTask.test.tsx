import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const suspendFn = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const destroyTaskTerminals = vi.hoisted(() => vi.fn());
const workspaceClient = vi.hoisted(() => ({
  getAll: vi.fn().mockResolvedValue({}),
}));

const SUSPENDED_TASK_IDS_KEY = ["suspension", "suspendedTaskIds"];

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    suspension: {
      suspendedTaskIds: {
        queryKey: () => SUSPENDED_TASK_IDS_KEY,
      },
      pathFilter: () => ({ queryKey: ["suspension"] }),
      suspend: {
        mutationOptions: (options: Record<string, unknown>) => ({
          mutationFn: (input: unknown) => suspendFn(input),
          ...options,
        }),
      },
    },
  }),
  useHostTRPCClient: () => ({
    workspace: { getAll: { query: () => workspaceClient.getAll() } },
  }),
}));
vi.mock("@posthog/ui/features/focus/focusStore", () => ({
  useFocusStore: { getState: () => ({ session: null, disableFocus: vi.fn() }) },
}));
vi.mock("@posthog/ui/features/terminal/destroyTaskTerminals", () => ({
  destroyTaskTerminals,
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ info: vi.fn(), error: vi.fn() }) },
}));

import { useSuspendTask } from "./useSuspendTask";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useSuspendTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    suspendFn.mockResolvedValue(undefined);
    workspaceClient.getAll.mockResolvedValue({});
  });

  it("optimistically adds the task to the suspended set and calls suspend", async () => {
    const { result } = renderHook(() => useSuspendTask(), { wrapper });
    await result.current.suspendTask({ taskId: "t1" });
    expect(suspendFn).toHaveBeenCalledWith({
      taskId: "t1",
      reason: "manual",
    });
    expect(destroyTaskTerminals).toHaveBeenCalledWith("t1");
  });

  it("rolls back the optimistic suspended set when suspend fails", async () => {
    suspendFn.mockRejectedValueOnce(new Error("boom"));
    const seen: Array<string[] | undefined> = [];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const localWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useSuspendTask(), {
      wrapper: localWrapper,
    });

    await expect(result.current.suspendTask({ taskId: "t1" })).rejects.toThrow(
      "boom",
    );
    seen.push(queryClient.getQueryData<string[]>(SUSPENDED_TASK_IDS_KEY));
    expect(seen[0] ?? []).not.toContain("t1");
    expect(destroyTaskTerminals).not.toHaveBeenCalled();
  });
});
