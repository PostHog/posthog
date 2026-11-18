export type SettingsCategory =
  | "general"
  | "appearance"
  | "notifications"
  | "plan-usage"
  | "cost-management"
  | "workspaces"
  | "worktrees"
  | "environments"
  | "cloud-environments"
  | "agents"
  | "task-agent-defaults"
  | "skills"
  | "mcp-servers"
  | "personalization"
  | "terminal"
  | "harness"
  | "shortcuts"
  | "github"
  | "slack"
  | "signals"
  | "advanced"
  | "discord";

const SETTINGS_CATEGORIES: readonly SettingsCategory[] = [
  "general",
  "appearance",
  "notifications",
  "plan-usage",
  "cost-management",
  "workspaces",
  "worktrees",
  "environments",
  "cloud-environments",
  "agents",
  "task-agent-defaults",
  "skills",
  "mcp-servers",
  "personalization",
  "terminal",
  "harness",
  "shortcuts",
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
  appearance: "Appearance",
  notifications: "Notifications",
  "plan-usage": "Plan & usage",
  "cost-management": "Cost management",
  workspaces: "Workspaces",
  worktrees: "Worktrees",
  environments: "Environments",
  "cloud-environments": "Environments",
  agents: "Agents",
  "task-agent-defaults": "Model",
  skills: "Skills",
  "mcp-servers": "MCP servers",
  personalization: "Personalization",
  terminal: "Terminal",
  harness: "Harness",
  shortcuts: "Shortcuts",
  github: "GitHub",
  slack: "Slack",
  signals: "Self-driving",
  advanced: "Advanced",
  discord: "Discord",
};

// Pages whose changes show in the app itself, so the dialog drops its backdrop
// to let the reader watch them land.
const APP_REVEALING_PAGES: ReadonlySet<SettingsCategory> = new Set([
  "appearance",
]);

export function settingsPageRevealsApp(category: SettingsCategory): boolean {
  return APP_REVEALING_PAGES.has(category);
}

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
