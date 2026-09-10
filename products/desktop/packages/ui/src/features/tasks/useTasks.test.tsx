import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";
import { taskKeys } from "./taskKeys";
import { useTasks } from "./useTasks";

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getTasks: vi.fn() }),
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
});
