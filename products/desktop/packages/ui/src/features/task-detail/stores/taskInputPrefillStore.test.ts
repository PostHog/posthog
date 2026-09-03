import { beforeEach, describe, expect, it } from "vitest";

import { useTaskInputPrefillStore } from "./taskInputPrefillStore";

describe("taskInputPrefillStore", () => {
  beforeEach(() => {
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  it("takes agent action attribution once", () => {
    const attribution = {
      action_id: "task-1:tool-1:0",
      source_task_id: "task-1",
      tool_call_id: "tool-1",
      action_index: 0,
    };
    useTaskInputPrefillStore.getState().setPrefill({
      initialPrompt: "Investigate this",
      agentActionAttribution: attribution,
    });

    expect(
      useTaskInputPrefillStore.getState().takeAgentActionAttribution(),
    ).toEqual(attribution);
    expect(
      useTaskInputPrefillStore.getState().takeAgentActionAttribution(),
    ).toBeUndefined();
    expect(useTaskInputPrefillStore.getState().prefill.initialPrompt).toBe(
      "Investigate this",
    );
  });
});
