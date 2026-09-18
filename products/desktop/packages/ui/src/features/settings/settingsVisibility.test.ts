import { describe, expect, it } from "vitest";
import { getHiddenSettingsCategories } from "./settingsVisibility";

describe("getHiddenSettingsCategories", () => {
  it.each([
    {
      name: "shows all categories when every capability is available",
      input: {
        localWorkspaces: true,
        quickAskAvailable: true,
      },
      expected: [],
    },
    {
      name: "hides host-specific categories without local workspaces",
      input: {
        localWorkspaces: false,
        quickAskAvailable: true,
      },
      expected: ["workspaces", "worktrees", "terminal", "harness", "discord"],
    },
    {
      // The page's only content when the panel is unavailable is a dead-end
      // "not available in this build" message, so hide it (web hosts and
      // packaged desktop without the prototype gate).
      name: "hides quick-ask when the panel is unavailable",
      input: {
        localWorkspaces: true,
      },
      expected: ["quick-ask"],
    },
  ])("$name", ({ input, expected }) => {
    expect([...getHiddenSettingsCategories(input)]).toEqual(expected);
  });
});
