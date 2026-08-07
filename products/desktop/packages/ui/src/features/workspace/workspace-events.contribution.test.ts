import type { HostTrpcClient } from "@posthog/host-router/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ImperativeQueryClient } from "../../shell/queryClient";

const invalidateQueries = vi.hoisted(() => vi.fn());
const setQueriesData = vi.hoisted(() => vi.fn());
const setQueryData = vi.hoisted(() => vi.fn());
const queryClient = {
  invalidateQueries,
  setQueriesData,
  setQueryData,
} as unknown as ImperativeQueryClient;

const toast = vi.hoisted(() => ({ error: vi.fn(), info: vi.fn() }));
vi.mock("../../primitives/toast", () => ({ toast }));

import { WORKSPACE_QUERY_KEY } from "./identifiers";
import { WorkspaceEventsContribution } from "./workspace-events.contribution";

function makeClient() {
  const handlers: Record<string, (data: unknown) => void> = {};
  const event = (name: string) => ({
    subscribe: (
      _input: undefined,
      opts: { onData: (data: unknown) => void },
    ) => {
      handlers[name] = opts.onData;
      return { unsubscribe: vi.fn() };
    },
  });
  return {
    handlers,
    workspace: {
      onError: event("onError"),
      onPromoted: event("onPromoted"),
      onBranchChanged: event("onBranchChanged"),
      onLinkedBranchChanged: event("onLinkedBranchChanged"),
      onTaskPrInfoChanged: event("onTaskPrInfoChanged"),
    },
  };
}

describe("WorkspaceEventsContribution", () => {
  beforeEach(() => vi.clearAllMocks());

  it("subscribes to all five workspace events on start", () => {
    const client = makeClient();
    new WorkspaceEventsContribution(
      client as unknown as HostTrpcClient,
      queryClient,
    ).start();
    expect(Object.keys(client.handlers).sort()).toEqual([
      "onBranchChanged",
      "onError",
      "onLinkedBranchChanged",
      "onPromoted",
      "onTaskPrInfoChanged",
    ]);
  });

  it("onPromoted invalidates the workspace query and toasts", () => {
    const client = makeClient();
    new WorkspaceEventsContribution(
      client as unknown as HostTrpcClient,
      queryClient,
    ).start();
    client.handlers.onPromoted({ fromBranch: "feat/x" });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: WORKSPACE_QUERY_KEY,
    });
    expect(toast.info).toHaveBeenCalled();
  });

  it("onError toasts without invalidating", () => {
    const client = makeClient();
    new WorkspaceEventsContribution(
      client as unknown as HostTrpcClient,
      queryClient,
    ).start();
    client.handlers.onError({ message: "boom" });
    expect(toast.error).toHaveBeenCalledWith("Workspace error", {
      description: "boom",
    });
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("onBranchChanged invalidates the workspace query", () => {
    const client = makeClient();
    new WorkspaceEventsContribution(
      client as unknown as HostTrpcClient,
      queryClient,
    ).start();
    client.handlers.onBranchChanged(undefined);
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: WORKSPACE_QUERY_KEY,
    });
  });

  it("onTaskPrInfoChanged updates PR status and cached PR url caches", () => {
    const client = makeClient();
    new WorkspaceEventsContribution(
      client as unknown as HostTrpcClient,
      queryClient,
    ).start();
    client.handlers.onTaskPrInfoChanged({
      taskId: "task-1",
      prUrl: "https://github.com/o/r/pull/1",
      prUrls: ["https://github.com/o/r/pull/1"],
      prState: "open",
    });

    expect(setQueriesData).toHaveBeenCalledTimes(1);
    const [filters, updater] = setQueriesData.mock.calls[0];
    expect(filters.queryKey).toEqual([["workspace", "getTaskPrStatus"]]);
    expect(
      filters.predicate({
        queryKey: [
          ["workspace", "getTaskPrStatus"],
          { input: { taskId: "task-1" }, type: "query" },
        ],
      }),
    ).toBe(true);
    expect(
      filters.predicate({
        queryKey: [
          ["workspace", "getTaskPrStatus"],
          { input: { taskId: "task-2" }, type: "query" },
        ],
      }),
    ).toBe(false);
    expect(updater({ prState: null, hasDiff: true })).toEqual({
      prState: "open",
      hasDiff: true,
    });
    expect(updater(undefined)).toEqual({ prState: "open", hasDiff: false });

    expect(setQueryData).toHaveBeenCalledWith(
      [
        ["workspace", "getCachedPrUrl"],
        { input: { taskId: "task-1" }, type: "query" },
      ],
      {
        prUrl: "https://github.com/o/r/pull/1",
        prUrls: ["https://github.com/o/r/pull/1"],
      },
    );
  });
});
