import { sessionStoreSetters } from "@posthog/core/sessions/sessionStore";
import type { AcpMessage, AgentSession } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useSidebarSessionMap } from "./useSidebarSessionMap";

const RUN_ID = "run-1";
const TASK_ID = "task-1";

function seedSession() {
  sessionStoreSetters.setSession({
    taskRunId: RUN_ID,
    taskId: TASK_ID,
    events: [],
    messageQueue: [],
    pendingPermissions: new Map(),
    isPromptPending: false,
  } as unknown as AgentSession);
}

afterEach(() => {
  sessionStoreSetters.removeSession(RUN_ID);
});

describe("useSidebarSessionMap", () => {
  it("does not re-render when only events are appended", () => {
    seedSession();
    let renders = 0;
    renderHook(() => {
      renders++;
      return useSidebarSessionMap();
    });
    const baseline = renders;

    act(() => {
      sessionStoreSetters.appendEvents(RUN_ID, [
        { ts: 1, message: {} } as unknown as AcpMessage,
      ]);
    });

    expect(renders).toBe(baseline);
  });

  it("re-renders when a sidebar-relevant field changes", () => {
    seedSession();
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useSidebarSessionMap();
    });
    const baseline = renders;

    act(() => {
      sessionStoreSetters.updateSession(RUN_ID, { isPromptPending: true });
    });

    expect(renders).toBeGreaterThan(baseline);
    expect(result.current.get(TASK_ID)?.isPromptPending).toBe(true);
  });
});
