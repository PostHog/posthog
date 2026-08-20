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
        quickAskAvailable: true,
      },
      expected: [],
    },
    {
      name: "hides plan and usage without billing or spend analysis",
      input: {
        billingEnabled: false,
        spendAnalysisEnabled: false,
        localWorkspaces: true,
        quickAskAvailable: true,
      },
      expected: ["plan-usage"],
    },
    {
      name: "hides host-specific categories without local workspaces",
      input: {
        billingEnabled: true,
        spendAnalysisEnabled: true,
        localWorkspaces: false,
        quickAskAvailable: true,
      },
      expected: ["workspaces", "worktrees", "terminal", "harness", "discord"],
    },
    {
      // The channels layout uses a fixed nav, so the Sidebar page's
      // reorder/hide controls would have nothing to act on.
      name: "hides the sidebar page under the channels layout",
      input: {
        billingEnabled: true,
        spendAnalysisEnabled: true,
        localWorkspaces: true,
        channelsLayout: true,
        quickAskAvailable: true,
      },
      expected: ["sidebar"],
    },
    {
      // The page's only content when the panel is unavailable is a dead-end
      // "not available in this build" message, so hide it (web hosts and
      // packaged desktop without the prototype gate).
      name: "hides quick-ask when the panel is unavailable",
      input: {
        billingEnabled: true,
        spendAnalysisEnabled: true,
        localWorkspaces: true,
      },
      expected: ["quick-ask"],
    },
  ])("$name", ({ input, expected }) => {
    expect([...getHiddenSettingsCategories(input)]).toEqual(expected);
  });
});
