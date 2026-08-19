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
   * The channels layout replaces the customizable nav with a fixed one, so the
   * Sidebar page's controls have nothing to act on there.
   */
  channelsLayout?: boolean;
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
  channelsLayout = false,
  quickAskAvailable = false,
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
  // Better to hide the page than to leave one whose controls silently do
  // nothing. SettingsPanel also redirects direct navigation to a hidden
  // category, so a deep link can't reach it either.
  if (channelsLayout) {
    hiddenCategories.add("sidebar");
  }
  if (!quickAskAvailable) {
    hiddenCategories.add("quick-ask");
  }

  return hiddenCategories;
}
