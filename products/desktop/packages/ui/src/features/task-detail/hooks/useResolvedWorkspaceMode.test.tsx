import type { WorkspaceMode } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LocalWorkspaceMode } from "../../settings/settingsStore";

const hostState = vi.hoisted(() => ({ localWorkspaces: true }));
const cloudState = vi.hoisted(() => ({ enabled: false, flagsLoaded: false }));
const settingsState = vi.hoisted(() => ({
  lastUsedWorkspaceMode: "cloud" as WorkspaceMode,
  lastUsedLocalWorkspaceMode: "local" as LocalWorkspaceMode,
  setLastUsedWorkspaceMode: vi.fn(),
  setLastUsedLocalWorkspaceMode: vi.fn(),
  _hasHydrated: true,
}));

vi.mock("../../../shell/useHostCapabilities", () => ({
  useHostCapabilities: () => hostState,
}));
vi.mock("./useCloudModeEnabled", () => ({
  useCloudModeEnabled: () => cloudState.enabled,
}));
vi.mock("../../feature-flags/useFeatureFlagsLoaded", () => ({
  useFeatureFlagsLoaded: () => cloudState.flagsLoaded,
}));
vi.mock("../../settings/settingsStore", () => ({
  DEFAULT_WORKSPACE_MODE: "cloud",
  useSettingsStore: () => settingsState,
}));

import { useResolvedWorkspaceMode } from "./useResolvedWorkspaceMode";

const PENDING = {
  hasGithubIntegration: false,
  isLoadingIntegrations: true,
};
const SETTLED = {
  hasGithubIntegration: true,
  isLoadingIntegrations: false,
};

describe("useResolvedWorkspaceMode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hostState.localWorkspaces = true;
    cloudState.enabled = false;
    cloudState.flagsLoaded = false;
    settingsState.lastUsedWorkspaceMode = "cloud";
    settingsState.lastUsedLocalWorkspaceMode = "local";
    settingsState._hasHydrated = true;
  });

  it("honors a cloud preference once the flag and integration land", () => {
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useResolvedWorkspaceMode>[0]) =>
        useResolvedWorkspaceMode(props),
      { initialProps: PENDING },
    );

    expect(result.current.workspaceMode).toBe("local");

    cloudState.enabled = true;
    cloudState.flagsLoaded = true;
    rerender(SETTLED);

    expect(result.current.workspaceMode).toBe("cloud");
  });

  it.each([
    ["local" as WorkspaceMode, "local"],
    ["worktree" as WorkspaceMode, "worktree"],
  ])("keeps a sticky %s pick when the signals settle", (stored, expected) => {
    settingsState.lastUsedWorkspaceMode = stored;
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;

    const { result } = renderHook(() => useResolvedWorkspaceMode(SETTLED));

    expect(result.current.workspaceMode).toBe(expected);
  });

  it("falls back to local when GitHub is not connected", () => {
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;

    const { result } = renderHook(() =>
      useResolvedWorkspaceMode({
        hasGithubIntegration: false,
        isLoadingIntegrations: false,
      }),
    );

    expect(result.current.workspaceMode).toBe("local");
  });

  it("ignores a cached integration until the live query settles", () => {
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;

    const { result, rerender } = renderHook(
      (props: Parameters<typeof useResolvedWorkspaceMode>[0]) =>
        useResolvedWorkspaceMode(props),
      {
        initialProps: {
          hasGithubIntegration: true,
          isLoadingIntegrations: true,
        },
      },
    );

    expect(result.current.workspaceMode).toBe("local");

    rerender({
      hasGithubIntegration: false,
      isLoadingIntegrations: false,
    });

    expect(result.current.workspaceMode).toBe("local");
  });

  it("collapses a worktree preference to local where worktrees can't run", () => {
    settingsState.lastUsedWorkspaceMode = "worktree";
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;

    const { result } = renderHook(() =>
      useResolvedWorkspaceMode({ ...SETTLED, allowWorktree: false }),
    );

    expect(result.current.workspaceMode).toBe("local");
  });

  it("remembers a user pick but not a context-driven override", () => {
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;
    const { result } = renderHook(() => useResolvedWorkspaceMode(SETTLED));

    act(() => result.current.setWorkspaceMode("worktree"));
    expect(result.current.workspaceMode).toBe("worktree");
    expect(settingsState.setLastUsedWorkspaceMode).toHaveBeenCalledWith(
      "worktree",
    );
    expect(settingsState.setLastUsedLocalWorkspaceMode).toHaveBeenCalledWith(
      "worktree",
    );

    vi.clearAllMocks();
    act(() => result.current.overrideWorkspaceMode("local"));
    expect(result.current.workspaceMode).toBe("local");
    expect(settingsState.setLastUsedWorkspaceMode).not.toHaveBeenCalled();
  });

  it("waits for the settings store to hydrate before resolving", () => {
    settingsState._hasHydrated = false;
    settingsState.lastUsedWorkspaceMode = "local";
    cloudState.enabled = true;
    cloudState.flagsLoaded = true;

    const { result, rerender } = renderHook(() =>
      useResolvedWorkspaceMode(SETTLED),
    );

    settingsState._hasHydrated = true;
    rerender();

    expect(result.current.workspaceMode).toBe("local");
  });

  it("pins cloud on a cloud-only host", () => {
    hostState.localWorkspaces = false;
    settingsState.lastUsedWorkspaceMode = "local";

    const { result } = renderHook(() => useResolvedWorkspaceMode(SETTLED));

    expect(result.current.workspaceMode).toBe("cloud");
  });
});
