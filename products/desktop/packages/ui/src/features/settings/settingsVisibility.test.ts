import { describe, expect, it } from "vitest";
import { getHiddenSettingsCategories } from "./settingsVisibility";

describe("getHiddenSettingsCategories", () => {
  it.each([
    {
      name: "shows all categories when every capability is available",
      input: {
        billingEnabled: true,
        spendAnalysisEnabled: true,
        localWorkspaces: true,
      },
      expected: [],
    },
    {
      name: "hides plan and usage without billing or spend analysis",
      input: {
        billingEnabled: false,
        spendAnalysisEnabled: false,
        localWorkspaces: true,
      },
      expected: ["plan-usage"],
    },
    {
      name: "hides host-specific categories without local workspaces",
      input: {
        billingEnabled: true,
        spendAnalysisEnabled: true,
        localWorkspaces: false,
      },
      expected: [
        "workspaces",
        "worktrees",
        "terminal",
        "claude-code",
        "discord",
        "updates",
      ],
    },
  ])("$name", ({ input, expected }) => {
    expect([...getHiddenSettingsCategories(input)]).toEqual(expected);
  });
});
