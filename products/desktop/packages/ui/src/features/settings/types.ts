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
  | "claude-code"
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
  "claude-code",
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
