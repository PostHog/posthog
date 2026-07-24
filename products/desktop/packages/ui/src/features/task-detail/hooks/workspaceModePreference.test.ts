import { describe, expect, it } from "vitest";
import { resolveWorkspaceModePreference } from "./workspaceModePreference";

describe("resolveWorkspaceModePreference", () => {
  it.each([
    ["cloud", true, true, "local", "cloud"],
    ["cloud", false, true, "local", "local"],
    ["cloud", true, false, "local", "local"],
    ["cloud", false, false, "local", "local"],
    ["cloud", false, true, "worktree", "worktree"],
    ["cloud", true, false, "worktree", "worktree"],
  ] as const)(
    "resolves %s (flag %s, integration %s, local fallback %s) to %s",
    (
      preferredMode,
      cloudModeEnabled,
      hasGithubIntegration,
      lastUsedLocalWorkspaceMode,
      expected,
    ) => {
      expect(
        resolveWorkspaceModePreference({
          preferredMode,
          cloudModeEnabled,
          hasGithubIntegration,
          lastUsedLocalWorkspaceMode,
        }),
      ).toBe(expected);
    },
  );

  it.each([
    ["local", true, true],
    ["local", false, false],
    ["worktree", true, false],
    ["worktree", false, true],
  ] as const)(
    "passes %s through untouched (flag %s, integration %s)",
    (preferredMode, cloudModeEnabled, hasGithubIntegration) => {
      expect(
        resolveWorkspaceModePreference({
          preferredMode,
          cloudModeEnabled,
          hasGithubIntegration,
          lastUsedLocalWorkspaceMode: "worktree",
        }),
      ).toBe(preferredMode);
    },
  );
});
