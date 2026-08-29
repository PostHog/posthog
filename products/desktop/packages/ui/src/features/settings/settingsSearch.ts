import {
  SETTINGS_PAGE_LABELS,
  type SettingsCategory,
} from "@posthog/ui/features/settings/types";

export interface SettingsSearchEntry {
  category: SettingsCategory;
  label: string;
  keywords?: string[];
}

// Hand-curated index of the settings each page holds. When a page gains or
// loses a setting, update its entries here so search keeps finding it. Page
// display names come from SETTINGS_PAGE_LABELS, not repeated per entry.
export const SETTINGS_SEARCH_INDEX: SettingsSearchEntry[] = [
  {
    category: "general",
    label: "Theme",
    keywords: ["appearance", "light", "dark", "system"],
  },
  {
    category: "general",
    label: "PostHog account",
    keywords: ["billing", "manage account", "email"],
  },
  {
    category: "general",
    label: "Mission Control overlay",
    keywords: ["macos", "logo"],
  },
  {
    category: "general",
    label: "Start in",
    keywords: ["plan mode", "initial task mode", "new tasks"],
  },
  {
    category: "general",
    label: "Effort",
    keywords: ["reasoning", "effort level"],
  },
  {
    category: "general",
    label: "Messaging",
    keywords: ["queue", "steer", "messaging mode"],
  },
  {
    category: "general",
    label: "Send messages with",
    keywords: ["enter", "cmd enter", "submit"],
  },
  {
    category: "general",
    label: "Convert long pastes to attachments",
    keywords: ["paste", "attachment", "long text"],
  },
  {
    category: "general",
    label: "Open diffs in",
    keywords: ["diff", "split pane", "editor"],
  },
  {
    category: "general",
    label: "Keep awake while agents work",
    keywords: ["sleep", "power", "battery"],
  },
  {
    category: "general",
    label: "Updates",
    keywords: [
      "version",
      "changelog",
      "check for updates",
      "download automatically",
      "update banner",
    ],
  },

  {
    category: "notifications",
    label: "System notifications",
    keywords: ["push", "native", "os notification", "alerts"],
  },
  {
    category: "notifications",
    label: "In-app toasts",
    keywords: ["toast"],
  },
  {
    category: "notifications",
    label: "Dock badge",
    keywords: ["badge", "unread dot"],
  },
  {
    category: "notifications",
    label: "Dock bounce",
    keywords: ["bounce", "attention"],
  },
  {
    category: "notifications",
    label: "Completion sound",
    keywords: ["sound", "volume", "chime", "custom sound"],
  },
  {
    category: "notifications",
    label: "Match speed to task length",
    keywords: ["sound speed", "playback rate", "scale sound", "task length"],
  },
  {
    category: "notifications",
    label: "Spoken narration",
    keywords: ["voice", "speech", "speak", "elevenlabs", "narration"],
  },
  {
    category: "notifications",
    label: "Send a test alert",
    keywords: ["test notification"],
  },

  {
    category: "personalization",
    label: "Custom instructions",
    keywords: ["agents.md", "claude.md", "instructions", "sync"],
  },
  {
    category: "personalization",
    label: "Hedgehog mode",
    keywords: ["hedgehog", "buddy", "fun"],
  },
  {
    category: "personalization",
    label: "Slot machine mode",
    keywords: ["slot", "lever", "fun"],
  },
  {
    category: "personalization",
    label: "Brainrot mode",
    keywords: ["video", "fun"],
  },

  {
    category: "plan-usage",
    label: "Plan & usage",
    keywords: ["billing", "credits", "spend", "subscription"],
  },
  {
    category: "cost-management",
    label: "Cost management",
    keywords: ["cost", "spend", "budget", "savings", "recommendations"],
  },
  {
    category: "cost-management",
    label: "Spend limits",
    keywords: [
      "budget",
      "warning",
      "stop line",
      "daily spend",
      "monthly spend",
    ],
  },
  {
    category: "cost-management",
    label: "Default model",
    keywords: ["cheaper model", "multiplier", "model cost", "switch model"],
  },
  {
    category: "cost-management",
    label: "Custom sandbox image",
    keywords: ["image", "tools", "ripgrep", "cloud runs", "setup"],
  },
  {
    category: "workspaces",
    label: "Workspaces",
    keywords: ["repos", "folders", "projects", "directories"],
  },
  {
    category: "worktrees",
    label: "Worktrees",
    keywords: ["git worktree", "cleanup", "disk"],
  },
  {
    category: "environments",
    label: "Environments",
    keywords: ["sandbox", "cloud environment", "image", "setup commands"],
  },
  {
    category: "terminal",
    label: "Terminal font",
    keywords: ["font", "monospace", "berkeley"],
  },
  {
    category: "terminal",
    label: "GPU rendering",
    keywords: ["webgl", "terminal"],
  },
  {
    category: "agents",
    label: "Agents",
    keywords: ["responders", "scouts", "signal sources", "setup agent"],
  },
  {
    category: "signals",
    label: "Self-driving",
    keywords: ["signals", "sources", "autostart", "base branches"],
  },
  {
    category: "skills",
    label: "Skills",
    keywords: ["slash commands"],
  },
  {
    category: "mcp-servers",
    label: "MCP servers",
    keywords: ["mcp", "tools", "connectors"],
  },
  {
    category: "harness",
    label: "Permission rules",
    keywords: ["allowed", "denied", "bypass permissions", "claude config"],
  },
  {
    category: "harness",
    label: "Claude Code & Codex",
    keywords: ["harness", "hooks", "memory", "claude", "codex"],
  },
  {
    category: "shortcuts",
    label: "Keyboard shortcuts",
    keywords: ["hotkeys", "keybindings"],
  },
  {
    category: "github",
    label: "GitHub",
    keywords: ["repositories", "connect", "integration"],
  },
  {
    category: "slack",
    label: "Slack",
    keywords: ["channels", "integration"],
  },
  {
    category: "discord",
    label: "Discord",
    keywords: ["presence", "integration"],
  },

  {
    category: "advanced",
    label: "Always create pull requests for cloud runs",
    keywords: ["auto publish", "draft pr", "pull request"],
  },
  {
    category: "advanced",
    label: "Compress command output",
    keywords: ["rtk", "tokens"],
  },
  {
    category: "advanced",
    label: "Reset onboarding and tours",
    keywords: ["tour", "tutorial"],
  },
  {
    category: "advanced",
    label: "Clear application storage",
    keywords: ["reset app", "delete data"],
  },
  {
    category: "advanced",
    label: "Debug logs for cloud runs",
    keywords: ["debug", "console output"],
  },
  {
    category: "advanced",
    label: "Developer mode",
    keywords: ["dev toolbar"],
  },
];

const MAX_RESULTS = 12;

function tokenScore(entry: SettingsSearchEntry, token: string): number {
  const label = entry.label.toLowerCase();
  if (label.startsWith(token)) return 3;
  if (label.includes(token)) return 2;
  const inKeywords = entry.keywords?.some((k) => k.includes(token));
  const page = SETTINGS_PAGE_LABELS[entry.category].toLowerCase();
  if (inKeywords || page.includes(token)) return 1;
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
