import { describe, expect, it } from "vitest";
import {
  resolveInitialWorkspaceMode,
  resolveWorkspaceModePreference,
} from "./workspaceModePreference";

describe("resolveInitialWorkspaceMode", () => {
  it.each([
    [undefined, true, true, null],
    ["local", true, false, "local"],
    ["worktree", true, false, "worktree"],
    ["cloud", false, true, "cloud"],
    ["local", false, true, null],
    ["worktree", false, true, null],
    ["cloud", true, false, null],
  ] as const)(
    "resolves %s with local workspaces %s and cloud enabled %s to %s",
    (mode, localWorkspaces, cloudModeEnabled, expected) => {
      expect(
        resolveInitialWorkspaceMode({
          mode,
          localWorkspaces,
          cloudModeEnabled,
        }),
      ).toBe(expected);
    },
  );
});

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
