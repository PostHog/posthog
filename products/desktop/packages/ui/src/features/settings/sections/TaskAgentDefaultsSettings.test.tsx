import { Theme } from "@radix-ui/themes";
import {
  configure,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Menu open/close and submenu reveals ride animations that starve under
// parallel suite load; the default 1s async timeout flakes.
configure({ asyncUtilTimeout: 5000 });

const saveMock = vi.hoisted(() => vi.fn());
const previewState = vi.hoisted(() => ({
  lastAdapter: null as string | null,
  setConfigOption: vi.fn(),
}));
// The personal preference the mocked hook reports; a test flips it to simulate
// a reset (which clears it to all-null) and re-renders.
const defaultsState = vi.hoisted(() => ({
  myPreferences: {
    runtime_adapter: null as string | null,
    model: null as string | null,
    reasoning_effort: null as string | null,
  },
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    selector: (state: {
      cloudRegion: string;
      currentProjectId: number;
      status: string;
    }) => unknown,
  ) =>
    selector({
      cloudRegion: "us",
      currentProjectId: 1,
      status: "authenticated",
    }),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/settings/hooks/useTaskAgentDefaults", () => ({
  useTaskAgentDefaults: () => ({
    teamPreferences: {
      runtime_adapter: "claude",
      model: "claude-fable-5",
      reasoning_effort: "high",
    },
    myPreferences: defaultsState.myPreferences,
    resolved: {
      runtime_adapter: "claude",
      model: "claude-fable-5",
      reasoning_effort: "high",
      source: "team",
    },
    isLoading: false,
    isSaving: false,
    save: saveMock,
    reset: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/task-detail/hooks/usePreviewConfig", () => ({
  usePreviewConfig: (adapter: string) => {
    previewState.lastAdapter = adapter;
    const models =
      adapter === "codex"
        ? [
            { name: "GPT-5.6 Sol", value: "gpt-5.6-sol" },
            { name: "GPT-5.6 Terra", value: "gpt-5.6-terra" },
          ]
        : [
            { name: "Claude Opus 5", value: "claude-opus-5" },
            { name: "Claude Fable 5", value: "claude-fable-5" },
          ];
    return {
      modelOption: {
        id: "model",
        name: "Model",
        type: "select",
        category: "model",
        currentValue: models[0].value,
        options: models,
      },
      thoughtOption: {
        id: "effort",
        name: "Effort",
        type: "select",
        category: "thought_level",
        currentValue: "high",
        options: [
          { name: "High", value: "high" },
          { name: "Max", value: "max" },
        ],
      },
      isLoading: false,
      setConfigOption: previewState.setConfigOption,
    };
  },
}));

import { TaskAgentDefaultsSettings } from "./TaskAgentDefaultsSettings";

// The submenus open on Base UI timers that RTL's act-wrapped waitFor never
// flushes in jsdom, so poll with plain sleeps instead of findByRole.
async function openSub(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const trigger = await screen.findByRole("menuitem", { name });
  await user.click(trigger);
  for (let attempt = 0; attempt < 100; attempt++) {
    if (screen.queryAllByRole("menuitemradio").length > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("submenu did not open");
}

describe("TaskAgentDefaultsSettings", () => {
  beforeEach(() => {
    saveMock.mockClear();
    previewState.setConfigOption.mockClear();
    previewState.lastAdapter = null;
    defaultsState.myPreferences = {
      runtime_adapter: null,
      model: null,
      reasoning_effort: null,
    };
  });

  // Switching harness used to save {adapter, null, null}, which wiped a stored
  // personal default and flipped the derived harness straight back — a dead
  // control. The switch must persist nothing until a model pick completes the
  // triple, which then carries the new harness.
  it("holds a harness switch unsaved until a model pick completes the triple", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <TaskAgentDefaultsSettings />
      </Theme>,
    );

    // Nothing stored: the pill shows the inherited default behind the marker.
    const trigger = screen.getByRole("button", {
      name: /Model and reasoning/,
    });
    expect(trigger).toHaveTextContent("Default ·");

    await user.click(trigger);
    await openSub(user, /^Harness/);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Codex" }));

    // The switch itself: control moves, nothing is saved, and a mid-switch
    // browse no longer claims to be the inherited default.
    expect(saveMock).not.toHaveBeenCalled();
    expect(previewState.lastAdapter).toBe("codex");
    expect(trigger).not.toHaveTextContent("Default ·");

    await openSub(user, /^Model/);
    const model = await screen.findByRole("menuitemradio", {
      name: /GPT-5.6 Terra/,
    });
    fireEvent.click(model);

    expect(saveMock).toHaveBeenCalledTimes(1);
    expect(saveMock).toHaveBeenCalledWith({
      runtime_adapter: "codex",
      model: "gpt-5.6-terra",
      reasoning_effort: null,
    });
  });

  // Mid-switch the stored triple still names the previous harness's model. A
  // reasoning-only pick must pair the effort with the new harness's own seated
  // model, or it saves a preference (Codex adapter + Claude model) no surface
  // can apply.
  it("pairs a reasoning-only pick with the new harness's model after a switch", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <TaskAgentDefaultsSettings />
      </Theme>,
    );

    const trigger = screen.getByRole("button", {
      name: /Model and reasoning/,
    });

    await user.click(trigger);
    await openSub(user, /^Harness/);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Codex" }));
    expect(previewState.lastAdapter).toBe("codex");

    await openSub(user, /^Reasoning/);
    const level = await screen.findByRole("menuitemradio", { name: "Max" });
    fireEvent.click(level);

    expect(saveMock).toHaveBeenCalledTimes(1);
    expect(saveMock).toHaveBeenCalledWith({
      runtime_adapter: "codex",
      model: "gpt-5.6-sol",
      reasoning_effort: "max",
    });
  });

  // Switching harness then resetting an existing default used to leave the
  // picker stuck on the previewed harness: reset clears the personal model, so
  // the "stored adapter matches pending" clear never fires. The control must
  // snap back to the inherited project harness instead.
  it("drops a pending harness browse when the default is reset", async () => {
    defaultsState.myPreferences = {
      runtime_adapter: "claude",
      model: "claude-fable-5",
      reasoning_effort: "high",
    };
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { rerender } = render(
      <Theme>
        <TaskAgentDefaultsSettings />
      </Theme>,
    );

    const trigger = screen.getByRole("button", {
      name: /Model and reasoning/,
    });
    await user.click(trigger);
    await openSub(user, /^Harness/);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Codex" }));
    expect(previewState.lastAdapter).toBe("codex");

    // Reset clears the personal default: myPreferences flips to all-null.
    defaultsState.myPreferences = {
      runtime_adapter: null,
      model: null,
      reasoning_effort: null,
    };
    rerender(
      <Theme>
        <TaskAgentDefaultsSettings />
      </Theme>,
    );

    // The pending browse is dropped, so the picker returns to the inherited
    // (Claude) harness rather than staying on Codex.
    await waitFor(() => expect(previewState.lastAdapter).toBe("claude"));
    expect(trigger).toHaveTextContent("Default ·");
  });
});
