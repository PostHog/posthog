import { sessionStoreSetters } from "@posthog/core/sessions/sessionStore";
import type { AcpMessage, AgentSession } from "@posthog/shared";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useCloudEventSummary } from "./useCloudEventSummary";

function update(ts: number, value: Record<string, unknown>): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update: value },
    },
  };
}
afterEach(() => {
  cleanup();
  sessionStoreSetters.removeSession("run-1");
});

describe("useCloudEventSummary", () => {
  it("shares snapshots across consumers, ignores text, and releases tools on eviction", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-1",
      taskId: "task-1",
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
    } as unknown as AgentSession);
    let renders = 0;
    const first = renderHook(() => {
      renders++;
      return useCloudEventSummary("task-1");
    });
    const second = renderHook(() => useCloudEventSummary("task-1"));
    const baseline = renders;
    act(() =>
      sessionStoreSetters.appendEvents("run-1", [
        update(1, {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "Hello" },
        }),
      ]),
    );
    expect(renders).toBe(baseline);
    act(() =>
      sessionStoreSetters.appendEvents("run-1", [
        update(2, {
          sessionUpdate: "tool_call",
          toolCallId: "read-1",
          kind: "read",
          status: "in_progress",
        }),
      ]),
    );
    expect(first.result.current.toolCalls.size).toBe(1);
    expect(first.result.current).toBe(second.result.current);
    act(() => sessionStoreSetters.evictEvents("run-1"));
    expect(first.result.current.toolCalls.size).toBe(0);
    expect(first.result.current).toBe(second.result.current);
  });

  it("skips a hidden pane and catches up when enabled", () => {
    sessionStoreSetters.setSession({
      taskRunId: "run-1",
      taskId: "task-1",
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
    } as unknown as AgentSession);
    let enabled = false;
    let renders = 0;
    const { result, rerender } = renderHook(() => {
      renders++;
      return useCloudEventSummary("task-1", enabled);
    });
    const baseline = renders;
    act(() =>
      sessionStoreSetters.appendEvents("run-1", [
        update(1, {
          sessionUpdate: "tool_call",
          toolCallId: "read-1",
          status: "completed",
        }),
      ]),
    );
    expect(renders).toBe(baseline);
    enabled = true;
    rerender();
    expect(result.current.toolCalls.size).toBe(1);
  });
});
