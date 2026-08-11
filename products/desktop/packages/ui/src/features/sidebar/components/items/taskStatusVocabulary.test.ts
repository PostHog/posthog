import { ArrowSquareIn, type Icon } from "@phosphor-icons/react";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";
import { describe, expect, it } from "vitest";

import { taskBadges, taskDot } from "./taskStatusVocabulary";

describe("taskDot", () => {
  it.each([
    ["a session here holds the prompt", { needsPermission: true }],
    ["the backend says the run is waiting", { awaitsInput: true }],
  ])("wants an answer when %s", (_case, waiting) => {
    // Both arrive alongside a run that still claims to be working, and both have to beat it:
    // a row that reads as "working" while the agent waits is the one the reader walks past.
    const dot = taskDot({
      ...waiting,
      isGenerating: true,
      taskRunStatus: "in_progress",
      runMode: "background",
    });

    expect(dot.tone).toBe("blue");
    expect(dot.label).toBe("Needs your input");
  });
});

describe("taskBadges", () => {
  it.each([
    ["slack", SlackMark],
    ["signals_scout", ArrowSquareIn],
    ["error_tracking", ArrowSquareIn],
  ])("marks a %s row with its source glyph", (originProduct, expected) => {
    const origin = taskBadges({ originProduct }).find(
      (badge) => badge.key === "origin",
    );

    expect(origin?.Icon).toBe(expected as Icon);
  });
});
