import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import type { TabsSnapshot } from "@posthog/shared";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPromptStore,
} from "@posthog/ui/shell/pendingTaskPromptStore";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  recoverPendingPrompt,
  settleFailedPromptRecord,
} from "./pendingPromptActions";

function reset(): void {
  usePendingTaskPromptStore.setState({ byKey: {}, _hasHydrated: true });
  useTaskInputPrefillStore.setState({ prefill: {} });
  browserTabsStore.getState().setSnapshot({ windows: [], tabs: [] });
}

function seedTabs(tabs: TabsSnapshot["tabs"]): void {
  browserTabsStore.getState().setSnapshot({ windows: [], tabs });
}

function backgroundTab(id: string): TabsSnapshot["tabs"][number] {
  return {
    id,
    windowId: "win-1",
    href: "/activity",
    viewState: null,
    dashboardId: null,
    taskId: null,
    channelId: null,
    channelSection: null,
    appView: null,
    position: 0,
    lastActiveAt: 0,
    createdAt: 0,
  };
}

function seedPrompt(key: string, promptText = "fix @a.ts"): void {
  pendingTaskPromptStoreApi.set(key, {
    promptText,
    attachments: [],
    contentXml: 'fix <file path="src/a.ts" />',
  });
}

describe("pendingPromptActions", () => {
  beforeEach(reset);
  afterEach(reset);

  it("stages the full prompt and keeps the record until the composer consumes it", () => {
    seedPrompt("k1");

    const recovered = recoverPendingPrompt("k1");

    expect(recovered).toBe(true);
    const { prefill } = useTaskInputPrefillStore.getState();
    // The file chip is preserved, so recovery restores attachments, not just text.
    expect(prefill.initialContent?.segments).toContainEqual({
      type: "chip",
      chip: { type: "file", id: "src/a.ts", label: "src/a.ts" },
    });
    // The composer is told which record to clear once it applies the content.
    expect(prefill.recoveredFromKey).toBe("k1");
    // The durable record survives until then, so a crash before the composer
    // mounts leaves the prompt recoverable on the next launch.
    expect(pendingTaskPromptStoreApi.get("k1")).toBeDefined();
  });

  it("recovers nothing and stages nothing when the record is already gone", () => {
    expect(recoverPendingPrompt("missing")).toBe(false);
    expect(
      useTaskInputPrefillStore.getState().prefill.initialContent,
    ).toBeUndefined();
  });

  it("recovers into the submitting tab instead of the active one", () => {
    seedTabs([backgroundTab("tab-bg")]);
    seedPrompt("k1");

    const recovered = recoverPendingPrompt("k1", "tab-bg");

    expect(recovered).toBe(true);
    // The background tab gets the composer as its durable target; the active
    // tab's composer is untouched, so no prefill is staged here.
    expect(
      useTaskInputPrefillStore.getState().prefill.initialContent,
    ).toBeUndefined();
    expect(browserTabsStore.getState().snapshot.tabs[0].href).toBe("/new");
    // The record survives until a composer applies it.
    expect(pendingTaskPromptStoreApi.get("k1")).toBeDefined();
  });

  it("leaves a closed submitting tab alone and keeps the record", () => {
    seedPrompt("k1");

    const recovered = recoverPendingPrompt("k1", "tab-gone");

    expect(recovered).toBe(true);
    expect(
      useTaskInputPrefillStore.getState().prefill.initialContent,
    ).toBeUndefined();
    // Next-launch recovery can still restore the prompt.
    expect(pendingTaskPromptStoreApi.get("k1")).toBeDefined();
  });

  it.each([
    { name: "open", tabs: [backgroundTab("tab-1")], recordSurvives: false },
    { name: "closed", tabs: [], recordSurvives: true },
  ])(
    "on an early failure it clears the record only while the origin tab keeps the draft ($name tab)",
    ({ tabs, recordSurvives }) => {
      seedTabs(tabs);
      seedPrompt("k1");

      settleFailedPromptRecord({
        recordKey: "k1",
        originTabId: "tab-1",
      });

      expect(pendingTaskPromptStoreApi.get("k1") !== undefined).toBe(
        recordSurvives,
      );
    },
  );

  it("on an early failure with tabs off it clears the record, because the composer still holds the draft", () => {
    seedPrompt("k1");

    settleFailedPromptRecord({ recordKey: "k1", originTabId: null });

    expect(pendingTaskPromptStoreApi.get("k1")).toBeUndefined();
  });

  it("on a late failure it recovers the prompt into the submitting tab and keeps the record", () => {
    seedPrompt("task-123");

    settleFailedPromptRecord({
      recordKey: "k1",
      createdTaskId: "task-123",
      originTabId: null,
    });

    expect(pendingTaskPromptStoreApi.get("task-123")).toBeDefined();
    const { prefill } = useTaskInputPrefillStore.getState();
    expect(prefill.recoveredFromKey).toBe("task-123");
  });

  it("on a late failure with a closed submitting tab it keeps the record for next launch", () => {
    seedPrompt("task-123");

    settleFailedPromptRecord({
      recordKey: "k1",
      createdTaskId: "task-123",
      originTabId: "tab-gone",
    });

    expect(pendingTaskPromptStoreApi.get("task-123")).toBeDefined();
    expect(
      useTaskInputPrefillStore.getState().prefill.initialContent,
    ).toBeUndefined();
  });

  it("settles nothing without a record key", () => {
    settleFailedPromptRecord({ recordKey: null, originTabId: null });
    expect(
      useTaskInputPrefillStore.getState().prefill.recoveredFromKey,
    ).toBeUndefined();
  });
});
