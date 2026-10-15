import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";
import { taskKeys } from "./taskKeys";
import { pinnedRecordsPollInterval, useTasks } from "./useTasks";

const mocks = vi.hoisted(() => ({ getTasks: vi.fn() }));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getTasks: mocks.getTasks }),
}));

vi.mock("@posthog/ui/features/auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: { id: 42 } }),
}));

describe("useTasks", () => {
  it("does not observe shared cache updates when unsubscribed", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    let renderCount = 0;
    const { result } = renderHook(
      () => {
        renderCount += 1;
        return useTasks(undefined, { enabled: false, subscribed: false });
      },
      { wrapper },
    );
    const queryKey = taskKeys.list({
      repository: undefined,
      createdBy: 42,
      internal: undefined,
    });

    expect(
      queryClient.getQueryCache().find({ queryKey })?.getObserversCount(),
    ).toBe(0);

    act(() => {
      queryClient.setQueryData(queryKey, [{ id: "task-1" }]);
    });

    expect(renderCount).toBe(1);
    expect(result.current.data).toBeUndefined();
  });

  it("keeps the previous page while a new page size loads", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const firstPage = [{ id: "task-1" }];
    mocks.getTasks
      .mockResolvedValueOnce(firstPage)
      .mockReturnValueOnce(new Promise(() => {}));
    const { result, rerender } = renderHook(
      ({ limit }) => useTasks({ limit }, { keepPreviousPage: true }),
      { wrapper, initialProps: { limit: 50 } },
    );
    await waitFor(() => expect(result.current.data).toEqual(firstPage));

    rerender({ limit: 51 });

    expect(result.current.data).toEqual(firstPage);
    expect(result.current.isLoading).toBe(false);
  });
});

describe("pinnedRecordsPollInterval", () => {
  it.each([
    { pins: undefined, pages: 1 },
    { pins: 100, pages: 1 },
    { pins: 101, pages: 2 },
    { pins: 1000, pages: 10 },
  ])(
    "waits one poll interval per page for $pins pins ($pages pages)",
    ({ pins, pages }) => {
      expect(pinnedRecordsPollInterval(pins)).toBe(
        pages * pinnedRecordsPollInterval(0),
      );
    },
  );
});
