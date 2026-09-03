import { beforeEach, describe, expect, it } from "vitest";

import { useTaskInputPrefillStore } from "./taskInputPrefillStore";

describe("taskInputPrefillStore", () => {
  beforeEach(() => {
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  it("consumes the matching agent action without clearing the prompt", () => {
    const attribution = {
      action_id: "task-1:tool-1:0",
      source_task_id: "task-1",
      tool_call_id: "tool-1",
      action_index: 0,
    };
    useTaskInputPrefillStore.getState().setPrefill({
      initialPrompt: "Investigate this",
      agentAction: { requestId: "request-1", attribution },
    });

    useTaskInputPrefillStore.getState().consumeAgentAction("request-1");

    expect(
      useTaskInputPrefillStore.getState().prefill.agentAction,
    ).toBeUndefined();
    expect(useTaskInputPrefillStore.getState().prefill.initialPrompt).toBe(
      "Investigate this",
    );
  });

  it("leaves a newer agent action alone", () => {
    const attribution = {
      action_id: "task-2:tool-2:0",
      source_task_id: "task-2",
      tool_call_id: "tool-2",
      action_index: 0,
    };
    useTaskInputPrefillStore.getState().setPrefill({
      agentAction: { requestId: "request-2", attribution },
    });

    useTaskInputPrefillStore.getState().consumeAgentAction("request-1");

    expect(useTaskInputPrefillStore.getState().prefill.agentAction).toEqual({
      requestId: "request-2",
      attribution,
    });
  });
});
