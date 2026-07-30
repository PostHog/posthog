import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { pinnedTasksApi } from "./taskMetaApi";
import { usePinnedTasks } from "./usePinnedTasks";

const authClient = vi.hoisted(() => ({
  getPinnedTaskIds: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => authClient,
}));

vi.mock("./taskMetaApi", () => ({
  pinnedTasksApi: {
    getPinnedTaskIds: vi.fn(),
    setPinned: vi.fn(),
    unpin: vi.fn(),
  },
}));

const mockedApi = vi.mocked(pinnedTasksApi);

describe("usePinnedTasks", () => {
  beforeEach(() => vi.clearAllMocks());

  function renderPinnedTasks() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return { ...renderHook(() => usePinnedTasks(), { wrapper }), client };
  }

  it("hydrates pins from the authenticated API", async () => {
    authClient.getPinnedTaskIds.mockResolvedValue(["task-1"]);

    const { result, client } = renderPinnedTasks();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isPinned("task-1")).toBe(true);
    expect(authClient.getPinnedTaskIds).toHaveBeenCalledOnce();
    expect(
      client.getQueryCache().find({ queryKey: ["task-pins"] })?.meta,
    ).toMatchObject({ authScoped: true });
  });

  it("persists pin and unpin actions", async () => {
    authClient.getPinnedTaskIds.mockResolvedValue([]);
    mockedApi.setPinned.mockResolvedValue({
      taskId: "task-1",
      isPinned: true,
    });
    mockedApi.unpin.mockResolvedValue();
    const { result } = renderPinnedTasks();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() => result.current.togglePin("task-1"));
    expect(mockedApi.setPinned).toHaveBeenCalledWith("task-1", true);
    await waitFor(() => expect(result.current.isPinned("task-1")).toBe(true));

    await act(() => result.current.unpin("task-1"));
    expect(mockedApi.unpin).toHaveBeenCalledWith("task-1");
    await waitFor(() => expect(result.current.isPinned("task-1")).toBe(false));
  });

  it("preserves rapid toggle order", async () => {
    authClient.getPinnedTaskIds.mockResolvedValue([]);
    mockedApi.setPinned
      .mockResolvedValueOnce({ taskId: "task-1", isPinned: true })
      .mockResolvedValueOnce({ taskId: "task-1", isPinned: false });
    const { result } = renderPinnedTasks();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() =>
      Promise.all([
        result.current.togglePin("task-1"),
        result.current.togglePin("task-1"),
      ]),
    );

    expect(mockedApi.setPinned.mock.calls).toEqual([
      ["task-1", true],
      ["task-1", false],
    ]);
    await waitFor(() => expect(result.current.isPinned("task-1")).toBe(false));
  });
});
