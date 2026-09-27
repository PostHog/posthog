import { describe, expect, it } from "vitest";
import { getHiddenSettingsCategories } from "./settingsVisibility";

describe("getHiddenSettingsCategories", () => {
  it.each([
    {
      name: "shows all categories when every capability is available",
      input: { localWorkspaces: true, taskBrowser: true },
      expected: [],
    },
    {
      name: "hides host-specific categories without local workspaces",
      input: { localWorkspaces: false, taskBrowser: false },
      expected: [
        "workspaces",
        "worktrees",
        "terminal",
        "harness",
        "discord",
        "browser",
      ],
    },
  ])("$name", ({ input, expected }) => {
    expect([...getHiddenSettingsCategories(input)]).toEqual(expected);
  });
});
