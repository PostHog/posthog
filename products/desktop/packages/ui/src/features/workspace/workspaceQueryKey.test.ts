import type { HostTrpcClient } from "@posthog/host-router/client";
import type { HostRouter } from "@posthog/host-router/router";
import { partialMatchKey, QueryClient } from "@tanstack/react-query";
import { createTRPCOptionsProxy } from "@trpc/tanstack-react-query";
import { describe, expect, it } from "vitest";
import { WORKSPACE_QUERY_KEY } from "./identifiers";

// Guards against the hand-rolled-key trap: `trpc.workspace.getAll` registers
// under `[["workspace", "getAll"], { type: "query" }]`, so the shared
// invalidation key must be the partial filter `[["workspace", "getAll"]]`. A
// flat `["workspace", "getAll"]` partial-matches nothing, so every invalidator
// silently no-ops and freshly-created workspaces never land in the cache.
describe("WORKSPACE_QUERY_KEY", () => {
  it("partial-matches the real trpc.workspace.getAll query key", () => {
    const options = createTRPCOptionsProxy<HostRouter>({
      client: {} as HostTrpcClient,
      queryClient: new QueryClient(),
    });
    const registeredKey = options.workspace.getAll.queryOptions().queryKey;

    expect(partialMatchKey(registeredKey, WORKSPACE_QUERY_KEY)).toBe(true);
  });
});
