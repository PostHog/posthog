import type { SettingsCategory } from "@posthog/ui/features/settings/types";

export interface SettingsSearchEntry {
  category: SettingsCategory;
  /** The setting's visible label, shown as the result row. */
  label: string;
  /** The page name shown beside the result. */
  page: string;
  keywords?: string[];
}

// Hand-curated index of what lives on each page. When a page gains or loses a
// setting, update its entries here so search keeps finding it.
export const SETTINGS_SEARCH_INDEX: SettingsSearchEntry[] = [
  // General
  {
    category: "general",
    label: "Theme",
    page: "General",
    keywords: ["appearance", "light", "dark", "system"],
  },
  {
    category: "general",
    label: "PostHog account",
    page: "General",
    keywords: ["billing", "manage account", "email"],
  },
  {
    category: "general",
    label: "Mission Control overlay",
    page: "General",
    keywords: ["macos", "logo"],
  },
  {
    category: "general",
    label: "Start in",
    page: "General",
    keywords: ["plan mode", "initial task mode", "new tasks"],
  },
  {
    category: "general",
    label: "Effort",
    page: "General",
    keywords: ["reasoning", "effort level"],
  },
  {
    category: "general",
    label: "Messaging",
    page: "General",
    keywords: ["queue", "steer", "messaging mode"],
  },
  {
    category: "general",
    label: "Send messages with",
    page: "General",
    keywords: ["enter", "cmd enter", "submit"],
  },
  {
    category: "general",
    label: "Convert long pastes to attachments",
    page: "General",
    keywords: ["paste", "attachment", "long text"],
  },
  {
    category: "general",
    label: "Open diffs in",
    page: "General",
    keywords: ["diff", "split pane", "editor"],
  },
  {
    category: "general",
    label: "Keep awake while agents work",
    page: "General",
    keywords: ["sleep", "power", "battery"],
  },
  {
    category: "general",
    label: "Updates",
    page: "General",
    keywords: [
      "version",
      "changelog",
      "check for updates",
      "download automatically",
      "update banner",
    ],
  },

  // Notifications
  {
    category: "notifications",
    label: "System notifications",
    page: "Notifications",
    keywords: ["push", "native", "os notification", "alerts"],
  },
  {
    category: "notifications",
    label: "In-app toasts",
    page: "Notifications",
    keywords: ["toast"],
  },
  {
    category: "notifications",
    label: "Dock badge",
    page: "Notifications",
    keywords: ["badge", "unread dot"],
  },
  {
    category: "notifications",
    label: "Dock bounce",
    page: "Notifications",
    keywords: ["bounce", "attention"],
  },
  {
    category: "notifications",
    label: "Completion sound",
    page: "Notifications",
    keywords: ["sound", "volume", "chime", "custom sound"],
  },
  {
    category: "notifications",
    label: "Spoken narration",
    page: "Notifications",
    keywords: ["voice", "speech", "speak", "elevenlabs", "narration"],
  },
  {
    category: "notifications",
    label: "Send a test alert",
    page: "Notifications",
    keywords: ["test notification"],
  },

  // Personalization
  {
    category: "personalization",
    label: "Custom instructions",
    page: "Personalization",
    keywords: ["agents.md", "claude.md", "instructions", "sync"],
  },
  {
    category: "personalization",
    label: "Hedgehog mode",
    page: "Personalization",
    keywords: ["hedgehog", "buddy", "fun"],
  },
  {
    category: "personalization",
    label: "Slot machine mode",
    page: "Personalization",
    keywords: ["slot", "lever", "fun"],
  },
  {
    category: "personalization",
    label: "Brainrot mode",
    page: "Personalization",
    keywords: ["video", "fun"],
  },

  // Pages without per-row entries
  {
    category: "plan-usage",
    label: "Plan & usage",
    page: "Plan & usage",
    keywords: ["billing", "credits", "spend", "subscription"],
  },
  {
    category: "workspaces",
    label: "Workspaces",
    page: "Workspaces",
    keywords: ["repos", "folders", "projects", "directories"],
  },
  {
    category: "worktrees",
    label: "Worktrees",
    page: "Worktrees",
    keywords: ["git worktree", "cleanup", "disk"],
  },
  {
    category: "environments",
    label: "Environments",
    page: "Environments",
    keywords: ["sandbox", "cloud environment", "image", "setup commands"],
  },
  {
    category: "terminal",
    label: "Terminal font",
    page: "Terminal",
    keywords: ["font", "monospace", "berkeley"],
  },
  {
    category: "terminal",
    label: "GPU rendering",
    page: "Terminal",
    keywords: ["webgl", "terminal"],
  },
  {
    category: "agents",
    label: "Agents",
    page: "Agents",
    keywords: ["responders", "scouts", "signal sources", "setup agent"],
  },
  {
    category: "signals",
    label: "Self-driving",
    page: "Self-driving",
    keywords: ["signals", "sources", "autostart", "base branches"],
  },
  {
    category: "skills",
    label: "Skills",
    page: "Skills",
    keywords: ["slash commands"],
  },
  {
    category: "mcp-servers",
    label: "MCP servers",
    page: "MCP servers",
    keywords: ["mcp", "tools", "connectors"],
  },
  {
    category: "harness",
    label: "Permission rules",
    page: "Harness",
    keywords: ["allowed", "denied", "bypass permissions", "claude config"],
  },
  {
    category: "harness",
    label: "Claude Code & Codex",
    page: "Harness",
    keywords: ["harness", "hooks", "memory", "claude", "codex"],
  },
  {
    category: "shortcuts",
    label: "Keyboard shortcuts",
    page: "Shortcuts",
    keywords: ["hotkeys", "keybindings"],
  },
  {
    category: "github",
    label: "GitHub",
    page: "GitHub",
    keywords: ["repositories", "connect", "integration"],
  },
  {
    category: "slack",
    label: "Slack",
    page: "Slack",
    keywords: ["channels", "integration"],
  },
  {
    category: "discord",
    label: "Discord",
    page: "Discord",
    keywords: ["presence", "integration"],
  },
  {
    category: "sidebar",
    label: "Sidebar",
    page: "Sidebar",
    keywords: ["nav", "customize", "reorder"],
  },

  // Advanced
  {
    category: "advanced",
    label: "Always create pull requests for cloud runs",
    page: "Advanced",
    keywords: ["auto publish", "draft pr", "pull request"],
  },
  {
    category: "advanced",
    label: "Compress command output",
    page: "Advanced",
    keywords: ["rtk", "tokens"],
  },
  {
    category: "advanced",
    label: "Reset onboarding and tours",
    page: "Advanced",
    keywords: ["tour", "tutorial"],
  },
  {
    category: "advanced",
    label: "Clear application storage",
    page: "Advanced",
    keywords: ["reset app", "delete data"],
  },
  {
    category: "advanced",
    label: "Debug logs for cloud runs",
    page: "Advanced",
    keywords: ["debug", "console output"],
  },
  {
    category: "advanced",
    label: "Developer mode",
    page: "Advanced",
    keywords: ["dev toolbar"],
  },
];

const MAX_RESULTS = 12;

function tokenScore(entry: SettingsSearchEntry, token: string): number {
  const label = entry.label.toLowerCase();
  if (label.startsWith(token)) return 3;
  if (label.includes(token)) return 2;
  const inKeywords = entry.keywords?.some((k) => k.includes(token));
  if (inKeywords || entry.page.toLowerCase().includes(token)) return 1;
  return 0;
}

/**
 * Case-insensitive search over the settings index. Every whitespace-separated
 * token must match the entry's label, keywords, or page name.
 */
export function searchSettings(
  query: string,
  hiddenCategories: ReadonlySet<SettingsCategory>,
): SettingsSearchEntry[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return [];

  return SETTINGS_SEARCH_INDEX.filter(
    (entry) => !hiddenCategories.has(entry.category),
  )
    .map((entry) => {
      let score = 0;
      for (const token of tokens) {
        const s = tokenScore(entry, token);
        if (s === 0) return { entry, score: 0 };
        score += s;
      }
      return { entry, score };
    })
    .filter((scored) => scored.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, MAX_RESULTS)
    .map((scored) => scored.entry);
}
