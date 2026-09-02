import type { SettingsCategory } from "@posthog/ui/features/settings/types";

// Settings that only make sense with a local filesystem/host (local worktrees,
// terminal, the local `claude` CLI, the desktop app itself). Hidden on the
// cloud-only web host.
const LOCAL_ONLY_CATEGORIES: ReadonlySet<SettingsCategory> = new Set([
  "workspaces",
  "worktrees",
  "terminal",
  "harness",
  "discord",
]);

interface SettingsVisibility {
  billingEnabled: boolean;
  spendAnalysisEnabled: boolean;
  localWorkspaces: boolean;
  /**
   * The quick-ask panel exists on this host and build. Off (web, and packaged
   * desktop without the prototype gate) hides its settings page, whose only
   * content otherwise is an "unavailable" message.
   */
  quickAskAvailable?: boolean;
}

export function getHiddenSettingsCategories({
  billingEnabled,
  spendAnalysisEnabled,
  localWorkspaces,
  quickAskAvailable = false,
}: SettingsVisibility): ReadonlySet<SettingsCategory> {
  // SettingsPanel drops these from its nav and its search, and redirects
  // direct navigation to one, so a deep link can't reach them either.
  const hiddenCategories = new Set<SettingsCategory>();

  if (!billingEnabled && !spendAnalysisEnabled) {
    hiddenCategories.add("plan-usage");
  }
  if (!spendAnalysisEnabled) {
    hiddenCategories.add("cost-management");
  }
  if (!localWorkspaces) {
    for (const category of LOCAL_ONLY_CATEGORIES) {
      hiddenCategories.add(category);
    }
  }
  if (!quickAskAvailable) {
    hiddenCategories.add("quick-ask");
  }

  return hiddenCategories;
}
