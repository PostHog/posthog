import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { routeState } = vi.hoisted(() => ({
  routeState: { tabId: undefined as string | undefined },
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({ select }: { select: (state: unknown) => unknown }) =>
    select({ location: { state: routeState } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsWorld", () => ({
  useChannelsWorld: () => false,
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => {
    const prefill = useTaskInputPrefillStore((state) => state.prefill);
    return { ...prefill, taskInputRequestId: prefill.requestId };
  },
}));
vi.mock("./TaskInput", () => ({
  TaskInput: ({
    sessionId,
    initialPrompt,
    initialPromptKey,
  }: {
    sessionId: string;
    initialPrompt?: string;
    initialPromptKey?: string;
  }) => {
    const [prompt, setPrompt] = useState("");
    useEffect(() => {
      if (!initialPrompt || !initialPromptKey) return;
      setPrompt(initialPrompt);
      useTaskInputPrefillStore.getState().consumePrompt(initialPromptKey);
    }, [initialPrompt, initialPromptKey]);
    return (
      <input
        aria-label="Prompt"
        data-session-id={sessionId}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
      />
    );
  },
}));

import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { useEffect, useState } from "react";
import { NewTaskScreen } from "./NewTaskScreen";

describe("NewTaskScreen", () => {
  beforeEach(() => {
    routeState.tabId = undefined;
    useTaskInputPrefillStore.setState({
      prefill: { requestId: "req-1", initialPrompt: "Check the build" },
    });
  });

  it("keeps the prompt when navigation assigns its tab", () => {
    const { rerender } = render(<NewTaskScreen />);

    routeState.tabId = "tab-1";
    rerender(<NewTaskScreen />);

    expect(screen.getByRole("textbox", { name: "Prompt" })).toHaveValue(
      "Check the build",
    );
    expect(screen.getByRole("textbox", { name: "Prompt" })).toHaveAttribute(
      "data-session-id",
      "task-input:tab-1",
    );
    expect(
      useTaskInputPrefillStore.getState().prefill.initialPrompt,
    ).toBeUndefined();
  });
});
