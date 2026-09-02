import type { WorkspaceMode } from "@posthog/shared";
import { useCallback, useEffect, useRef, useState } from "react";
import { useHostCapabilities } from "../../../shell/useHostCapabilities";
import { useFeatureFlagsLoaded } from "../../feature-flags/useFeatureFlagsLoaded";
import {
  DEFAULT_WORKSPACE_MODE,
  type LocalWorkspaceMode,
  useSettingsStore,
} from "../../settings/settingsStore";
import { useCloudModeEnabled } from "./useCloudModeEnabled";
import {
  areCloudSignalsSettled,
  resolveWorkspaceModePreference,
} from "./workspaceModePreference";

export interface UseResolvedWorkspaceModeInput {
  hasGithubIntegration: boolean;
  isLoadingIntegrations: boolean;
  pinCloud?: boolean;
  allowWorktree?: boolean;
}

export interface ResolvedWorkspaceMode {
  workspaceMode: WorkspaceMode;
  setWorkspaceMode: (mode: WorkspaceMode) => void;
  overrideWorkspaceMode: (mode: WorkspaceMode) => void;
}

export function useResolvedWorkspaceMode({
  hasGithubIntegration,
  isLoadingIntegrations,
  pinCloud = false,
  allowWorktree = true,
}: UseResolvedWorkspaceModeInput): ResolvedWorkspaceMode {
  const {
    lastUsedWorkspaceMode,
    lastUsedLocalWorkspaceMode,
    setLastUsedWorkspaceMode,
    setLastUsedLocalWorkspaceMode,
    _hasHydrated: settingsHydrated,
  } = useSettingsStore();
  const { localWorkspaces } = useHostCapabilities();
  const cloudModeEnabled = useCloudModeEnabled();
  const flagsLoaded = useFeatureFlagsLoaded();

  const storedMode = lastUsedWorkspaceMode || DEFAULT_WORKSPACE_MODE;
  const preferredMode: WorkspaceMode =
    allowWorktree || storedMode === "cloud" ? storedMode : "local";
  const localFallback: LocalWorkspaceMode = allowWorktree
    ? lastUsedLocalWorkspaceMode
    : "local";

  const [workspaceMode, setWorkspaceModeState] = useState<WorkspaceMode>(() => {
    if (pinCloud || !localWorkspaces) return "cloud";
    return resolveWorkspaceModePreference({
      preferredMode,
      cloudModeEnabled,
      hasGithubIntegration: hasGithubIntegration && !isLoadingIntegrations,
      lastUsedLocalWorkspaceMode: localFallback,
    });
  });

  const cloudSignalsSettled = areCloudSignalsSettled({
    cloudModeEnabled,
    flagsLoaded,
    isLoadingIntegrations,
  });

  const didResolveRef = useRef(false);
  useEffect(() => {
    if (didResolveRef.current) return;
    if (!settingsHydrated) return;
    if (pinCloud) {
      didResolveRef.current = true;
      return;
    }
    if (preferredMode === "cloud" && !cloudSignalsSettled) return;
    didResolveRef.current = true;
    if (!localWorkspaces) return;
    setWorkspaceModeState(
      resolveWorkspaceModePreference({
        preferredMode,
        cloudModeEnabled,
        hasGithubIntegration,
        lastUsedLocalWorkspaceMode: localFallback,
      }),
    );
  }, [
    settingsHydrated,
    pinCloud,
    preferredMode,
    cloudSignalsSettled,
    localWorkspaces,
    cloudModeEnabled,
    hasGithubIntegration,
    localFallback,
  ]);

  const setWorkspaceMode = useCallback(
    (mode: WorkspaceMode) => {
      didResolveRef.current = true;
      setWorkspaceModeState(mode);
      setLastUsedWorkspaceMode(mode);
      if (mode !== "cloud") setLastUsedLocalWorkspaceMode(mode);
    },
    [setLastUsedWorkspaceMode, setLastUsedLocalWorkspaceMode],
  );

  const overrideWorkspaceMode = useCallback((mode: WorkspaceMode) => {
    didResolveRef.current = true;
    setWorkspaceModeState(mode);
  }, []);

  return { workspaceMode, setWorkspaceMode, overrideWorkspaceMode };
}
