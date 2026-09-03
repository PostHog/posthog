import { beforeEach, describe, expect, it, vi } from "vitest";

const navigateToChannelNewTask = vi.fn();
const navigateToNewTask = vi.fn();

vi.mock("./navigationBridge", () => ({
  navigateToChannelNewTask: (...args: unknown[]) =>
    navigateToChannelNewTask(...args),
  navigateToNewTask: () => navigateToNewTask(),
  navigateToChannelTask: vi.fn(),
  navigateToTaskDetail: vi.fn(),
  navigateToFolderSettings: vi.fn(),
}));
vi.mock("@posthog/di/container", () => ({
  resolveService: vi.fn(),
  resolveServiceOptional: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  setActiveTaskContext: vi.fn(),
}));

import {
  resetCurrentChannel,
  useCurrentChannelStore,
} from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { openTaskInput } from "./useOpenTask";

describe("openTaskInput channel scoping", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCurrentChannelStore.setState({ currentChannelId: null });
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  // Without the channels layout nothing sets a current channel, so creates must
  // land where they always did rather than being pulled into a channel.
  it("opens the unscoped new task when no channel is current", () => {
    openTaskInput();
    expect(navigateToNewTask).toHaveBeenCalledTimes(1);
    expect(navigateToChannelNewTask).not.toHaveBeenCalled();
  });

  it("routes into the current channel once one is scoped", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    openTaskInput();
    expect(navigateToChannelNewTask).toHaveBeenCalledWith("chan-1");
    expect(navigateToNewTask).not.toHaveBeenCalled();
  });

  it("carries prefill into the channel route", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    openTaskInput({ initialPrompt: "ship it" });
    expect(navigateToChannelNewTask).toHaveBeenCalledWith("chan-1");
  });

  // A caller that names its channel must not be overridden by whatever the
  // sidebar happens to be scoped to.
  it("prefers an explicit channel over the scoped one", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    openTaskInput({ channelId: "chan-9" });
    expect(navigateToChannelNewTask).toHaveBeenCalledWith("chan-9");
  });

  // useArchiveTask and friends pass `unscoped` deliberately; a scoped channel
  // silently hijacking that is how a create lands in the wrong place.
  it("files nowhere when the caller asks, even while a channel is scoped", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    openTaskInput({ unscoped: true });
    expect(navigateToNewTask).toHaveBeenCalledTimes(1);
    expect(navigateToChannelNewTask).not.toHaveBeenCalled();
  });

  // The auth side effects call resetCurrentChannel() before openTaskInput() so
  // a project switch can't file the next task into the old project's channel.
  it("opens the unscoped new task again once the channel is reset", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    resetCurrentChannel();
    openTaskInput();
    expect(navigateToNewTask).toHaveBeenCalledTimes(1);
    expect(navigateToChannelNewTask).not.toHaveBeenCalled();
  });

  it("replaces a stale prompt rather than leaving it to be re-applied", () => {
    openTaskInput({ initialPrompt: "old prompt" });
    const stale = useTaskInputPrefillStore.getState().prefill.requestId;

    openTaskInput({ channelId: "chan-1" });

    const { prefill } = useTaskInputPrefillStore.getState();
    expect(prefill.initialPrompt).toBeUndefined();
    expect(prefill.requestId).not.toBe(stale);
  });

  it("ties agent action attribution to the prefill request", () => {
    const attribution = {
      action_id: "task-1:tool-1:0",
      source_task_id: "task-1",
      tool_call_id: "tool-1",
      action_index: 0,
    };

    openTaskInput({ agentActionAttribution: attribution });

    const { prefill } = useTaskInputPrefillStore.getState();
    expect(prefill.agentAction).toEqual({
      requestId: prefill.requestId,
      attribution,
    });
  });
});

describe("taskInputPrefillStore.consumePrompt", () => {
  beforeEach(() => {
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  it("retires the prompt it was given", () => {
    useTaskInputPrefillStore.setState({
      prefill: { requestId: "r1", initialPrompt: "hello", folderId: "f1" },
    });

    useTaskInputPrefillStore.getState().consumePrompt("r1");

    const { prefill } = useTaskInputPrefillStore.getState();
    expect(prefill.initialPrompt).toBeUndefined();
    expect(prefill.requestId).toBeUndefined();
    // Folder scoping is not a one-shot prompt; it must survive.
    expect(prefill.folderId).toBe("f1");
  });

  it("leaves a newer prefill alone", () => {
    useTaskInputPrefillStore.setState({
      prefill: { requestId: "r2", initialPrompt: "newer" },
    });

    useTaskInputPrefillStore.getState().consumePrompt("r1");

    expect(useTaskInputPrefillStore.getState().prefill.initialPrompt).toBe(
      "newer",
    );
  });
});
