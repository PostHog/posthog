import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ client: null as unknown }));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => auth.client,
}));

import { useAuthenticatedQuery } from "./useAuthenticatedQuery";

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useAuthenticatedQuery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.client = null;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("holds a query with its own `enabled` until the client exists", async () => {
    // Without the gate this query fires before auth resolves, throws, and burns its retry
    // backoffs before the caller's loading state can clear.
    const queryFn = vi.fn().mockResolvedValue("data");

    const { rerender, result } = renderHook(
      () =>
        useAuthenticatedQuery(["thing"], queryFn, {
          enabled: true,
          retry: false,
        }),
      { wrapper },
    );

    expect(queryFn).not.toHaveBeenCalled();
    expect(result.current.isError).toBe(false);

    auth.client = { id: "client" };
    rerender();

    await waitFor(() => expect(result.current.data).toBe("data"));
    expect(queryFn).toHaveBeenCalledTimes(1);
  });

  it("still honours a caller that disables its query", () => {
    const queryFn = vi.fn().mockResolvedValue("data");
    auth.client = { id: "client" };

    renderHook(
      () => useAuthenticatedQuery(["thing"], queryFn, { enabled: false }),
      { wrapper },
    );

    expect(queryFn).not.toHaveBeenCalled();
  });
});
