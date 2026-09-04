import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPromptStore,
} from "@posthog/ui/shell/pendingTaskPromptStore";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  discardPendingPrompt,
  recoverPendingPrompt,
} from "./pendingPromptActions";

function reset(): void {
  usePendingTaskPromptStore.setState({ byKey: {}, _hasHydrated: true });
  useTaskInputPrefillStore.setState({ prefill: {} });
}

describe("pendingPromptActions", () => {
  beforeEach(reset);
  afterEach(reset);

  it("stages the full prompt and keeps the record until the composer consumes it", () => {
    pendingTaskPromptStoreApi.set("k1", {
      promptText: "fix @a.ts",
      attachments: [],
      contentXml: 'fix <file path="src/a.ts" />',
    });

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

  it("discards the prompt and opens an empty composer", () => {
    pendingTaskPromptStoreApi.set("k1", { promptText: "x", attachments: [] });
    discardPendingPrompt("k1");
    expect(pendingTaskPromptStoreApi.get("k1")).toBeUndefined();
    expect(
      useTaskInputPrefillStore.getState().prefill.initialContent,
    ).toBeUndefined();
  });
});
