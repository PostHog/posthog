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
  localWorkspaces: boolean;
}

export function getHiddenSettingsCategories({
  localWorkspaces,
}: SettingsVisibility): ReadonlySet<SettingsCategory> {
  // SettingsPanel drops these from its nav and its search, and redirects
  // direct navigation to one, so a deep link can't reach them either.
  const hiddenCategories = new Set<SettingsCategory>();

  if (!localWorkspaces) {
    for (const category of LOCAL_ONLY_CATEGORIES) {
      hiddenCategories.add(category);
    }
  }

  return hiddenCategories;
}
