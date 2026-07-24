import type { SettingsCategory } from "@posthog/ui/features/settings/types";

// Settings that only make sense with a local filesystem/host (local worktrees,
// terminal, the local `claude` CLI, the desktop app itself). Hidden on the
// cloud-only web host.
const LOCAL_ONLY_CATEGORIES: ReadonlySet<SettingsCategory> = new Set([
  "workspaces",
  "worktrees",
  "terminal",
  "claude-code",
  "discord",
  "updates",
]);

interface SettingsVisibility {
  billingEnabled: boolean;
  spendAnalysisEnabled: boolean;
  localWorkspaces: boolean;
}

export function getHiddenSettingsCategories({
  billingEnabled,
  spendAnalysisEnabled,
  localWorkspaces,
}: SettingsVisibility): ReadonlySet<SettingsCategory> {
  const hiddenCategories = new Set<SettingsCategory>();

  if (!billingEnabled && !spendAnalysisEnabled) {
    hiddenCategories.add("plan-usage");
  }
  if (!localWorkspaces) {
    for (const category of LOCAL_ONLY_CATEGORIES) {
      hiddenCategories.add(category);
    }
  }

  return hiddenCategories;
}
