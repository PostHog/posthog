export type SettingsCategory =
  | "general"
  | "notifications"
  | "plan-usage"
  | "cost-management"
  | "workspaces"
  | "worktrees"
  | "environments"
  | "cloud-environments"
  | "agents"
  | "skills"
  | "mcp-servers"
  | "personalization"
  | "terminal"
  | "harness"
  | "shortcuts"
  | "quick-ask"
  | "github"
  | "slack"
  | "signals"
  | "advanced"
  | "discord";

export const SETTINGS_CATEGORIES: readonly SettingsCategory[] = [
  "general",
  "notifications",
  "plan-usage",
  "cost-management",
  "workspaces",
  "worktrees",
  "environments",
  "cloud-environments",
  "agents",
  "skills",
  "mcp-servers",
  "personalization",
  "terminal",
  "harness",
  "shortcuts",
  "quick-ask",
  "github",
  "slack",
  "signals",
  "advanced",
  "discord",
];

export function isSettingsCategory(value: string): value is SettingsCategory {
  return (SETTINGS_CATEGORIES as readonly string[]).includes(value);
}

// The display name of each settings page. Single source for the sidebar nav
// and search. The `Record` type forces an entry per category, so a new page
// can't ship without a name. `cloud-environments` shares the Environments page.
export const SETTINGS_PAGE_LABELS: Record<SettingsCategory, string> = {
  general: "General",
  notifications: "Notifications",
  "plan-usage": "Plan & usage",
  "cost-management": "Cost management",
  workspaces: "Workspaces",
  worktrees: "Worktrees",
  environments: "Environments",
  "cloud-environments": "Environments",
  agents: "Agents",
  skills: "Skills",
  "mcp-servers": "MCP servers",
  personalization: "Personalization",
  terminal: "Terminal",
  harness: "Harness",
  shortcuts: "Shortcuts",
  "quick-ask": "Quick ask",
  github: "GitHub",
  slack: "Slack",
  signals: "Self-driving",
  advanced: "Advanced",
  discord: "Discord",
};

// The app restores the last location on startup, so a renamed category has to
// keep resolving for anyone whose remembered URL still names the old one.
const RENAMED_SETTINGS_CATEGORIES: Readonly<Record<string, SettingsCategory>> =
  {
    "claude-code": "harness",
    // The Updates page folded into General.
    updates: "general",
  };

export function resolveSettingsCategory(
  value: string,
): SettingsCategory | null {
  if (isSettingsCategory(value)) return value;
  return RENAMED_SETTINGS_CATEGORIES[value] ?? null;
}
