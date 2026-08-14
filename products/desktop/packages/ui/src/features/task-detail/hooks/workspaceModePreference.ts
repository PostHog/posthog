import type { WorkspaceMode } from "@posthog/shared";
import type { LocalWorkspaceMode } from "../../settings/settingsStore";

export interface WorkspaceModePreferenceInput {
  preferredMode: WorkspaceMode;
  cloudModeEnabled: boolean;
  hasGithubIntegration: boolean;
  lastUsedLocalWorkspaceMode: LocalWorkspaceMode;
}

export interface InitialWorkspaceModeInput {
  mode: WorkspaceMode | undefined;
  localWorkspaces: boolean;
  cloudModeEnabled: boolean;
}

export function resolveInitialWorkspaceMode({
  mode,
  localWorkspaces,
  cloudModeEnabled,
}: InitialWorkspaceModeInput): WorkspaceMode | null {
  if (!mode) return null;
  if (mode === "cloud") return cloudModeEnabled ? mode : null;
  return localWorkspaces ? mode : null;
}

// Cloud is only honoured when it works out of the box (flag on + GitHub
// connected); otherwise the preference falls back to the last local mode so
// users never start behind a connect-GitHub prompt.
export function resolveWorkspaceModePreference({
  preferredMode,
  cloudModeEnabled,
  hasGithubIntegration,
  lastUsedLocalWorkspaceMode,
}: WorkspaceModePreferenceInput): WorkspaceMode {
  if (preferredMode !== "cloud") return preferredMode;
  if (!cloudModeEnabled || !hasGithubIntegration) {
    return lastUsedLocalWorkspaceMode;
  }
  return "cloud";
}
