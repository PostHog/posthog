import { buildStaleFlagSuggestion } from "@posthog/core/setup/suggestions";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DiscoveredTaskDetailDialog } from "./DiscoveredTaskDetailDialog";

const { openTaskInput } = vi.hoisted(() => ({ openTaskInput: vi.fn() }));

vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput }));
vi.mock("../folders/useFolders", () => ({
  useFolders: () => ({ folders: [] }),
}));
vi.mock("../repo-files/useDetectedCloudRepository", () => ({
  useDetectedCloudRepository: () => null,
}));
vi.mock("../../shell/analytics", () => ({ track: vi.fn() }));
vi.mock("../editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

function staleFlagTask(): DiscoveredTask {
  const task = buildStaleFlagSuggestion({
    flagKey: "legacy-banner",
    referenceCount: 4,
    references: [
      { file: "src/a.ts", line: 4, method: "isFeatureEnabled" },
      { file: "src/b.ts", line: 22, method: "useFeatureFlag" },
    ],
  });
  if (!task) throw new Error("expected a suggestion");
  return { ...task, repoPath: "/repo" };
}

describe("DiscoveredTaskDetailDialog", () => {
  it("starts the stale-flag task with the assessment prompt, not a cleanup verdict", async () => {
    const user = userEvent.setup();
    render(
      <DiscoveredTaskDetailDialog task={staleFlagTask()} onClose={vi.fn()} />,
    );

    await user.click(screen.getByText("Implement as new task"));

    expect(openTaskInput).toHaveBeenCalledTimes(1);
    const { initialPrompt } = openTaskInput.mock.calls[0][0];

    expect(initialPrompt.startsWith("/cleaning-up-stale-feature-flags")).toBe(
      true,
    );
    expect(initialPrompt).toContain('"legacy-banner"');
    expect(initialPrompt).toContain("- src/a.ts:4 (isFeatureEnabled)");
    expect(initialPrompt).toContain("Before you edit any code:");
    expect(initialPrompt).toContain("Do not change the flag in PostHog.");
    expect(initialPrompt).not.toMatch(
      /winning branch|inline the |remove the flag/i,
    );
  });
});
