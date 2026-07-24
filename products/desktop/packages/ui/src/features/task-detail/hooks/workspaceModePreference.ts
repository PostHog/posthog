import type { WorkspaceMode } from "@posthog/shared";
import type { LocalWorkspaceMode } from "../../settings/settingsStore";

export interface WorkspaceModePreferenceInput {
  preferredMode: WorkspaceMode;
  cloudModeEnabled: boolean;
  hasGithubIntegration: boolean;
  lastUsedLocalWorkspaceMode: LocalWorkspaceMode;
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
