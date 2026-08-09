export type SettingsCategory =
  | "general"
  | "notifications"
  | "plan-usage"
  | "workspaces"
  | "worktrees"
  | "environments"
  | "cloud-environments"
  | "agents"
  | "skills"
  | "mcp-servers"
  | "personalization"
  | "sidebar"
  | "terminal"
  | "harness"
  | "shortcuts"
  | "github"
  | "slack"
  | "signals"
  | "updates"
  | "advanced"
  | "discord";

export const SETTINGS_CATEGORIES: readonly SettingsCategory[] = [
  "general",
  "notifications",
  "plan-usage",
  "workspaces",
  "worktrees",
  "environments",
  "cloud-environments",
  "agents",
  "skills",
  "mcp-servers",
  "personalization",
  "sidebar",
  "terminal",
  "harness",
  "shortcuts",
  "github",
  "slack",
  "signals",
  "updates",
  "advanced",
  "discord",
];

export function isSettingsCategory(value: string): value is SettingsCategory {
  return (SETTINGS_CATEGORIES as readonly string[]).includes(value);
}

// The app restores the last location on startup, so a renamed category has to
// keep resolving for anyone whose remembered URL still names the old one.
const RENAMED_SETTINGS_CATEGORIES: Readonly<Record<string, SettingsCategory>> =
  {
    "claude-code": "harness",
  };

export function resolveSettingsCategory(
  value: string,
): SettingsCategory | null {
  if (isSettingsCategory(value)) return value;
  return RENAMED_SETTINGS_CATEGORIES[value] ?? null;
}
