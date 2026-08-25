import {
  BugIcon,
  ChartLineIcon,
  ChatCircleTextIcon,
  ClipboardTextIcon,
  CursorClickIcon,
  DatabaseIcon,
  FlagIcon,
  FlaskIcon,
  type Icon,
  LightningIcon,
  PlayCircleIcon,
  PulseIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SquaresFourIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";

/**
 * The registry of PostHog object kinds an agent can embed in a message as
 * `<kind id="...">label</kind>` tags (see remarkObjectTags).
 *
 * Adding a kind here is all it takes for the inline chip: icon, labels, and
 * the click-through URL. Two opt-ins live elsewhere:
 * - a live hover preview needs a case in `PostHogAPIClient.getEvidencePreview`
 * - `block: true` needs a card renderer in `MessageChartCard`
 */
export interface ObjectKindDef {
  icon: Icon;
  /** Human name of the kind, e.g. "Insight". */
  kindLabel: string;
  /** Product the object comes from, e.g. "Product analytics". */
  source: string;
  /**
   * Project-relative PostHog web path, mirroring the canonical route table
   * (the `generate-app-url` MCP tool carries the same list). Return null when
   * this id has no direct page; omit when the kind has no canonical page.
   */
  webPath?: (encodedId: string, rawId: string) => string | null;
  /** Renders as a full chart card when the tag says display="block". */
  block?: boolean;
}

/**
 * The brand primary (orange in light, yellow in dark): PostHog object icons
 * carry it wherever they appear so PostHog-native artifacts read as PostHog at
 * a glance next to files and PRs. Passed as the phosphor `color` prop (an SVG
 * fill), which quill highlight rules can't reset the way `currentColor` can.
 */
export const POSTHOG_OBJECT_ICON_COLOR = "var(--primary)";

export const OBJECT_KINDS: Record<string, ObjectKindDef> = {
  insight: {
    icon: ChartLineIcon,
    kindLabel: "Insight",
    source: "Product analytics",
    webPath: (id) => `/insights/${id}`,
    block: true,
  },
  // For hogql the "id" is the SQL itself; the chip opens the SQL editor and
  // the hover card runs the query live.
  hogql: {
    icon: DatabaseIcon,
    kindLabel: "SQL query",
    source: "SQL editor",
    webPath: (id) => `/sql?open_query=${id}`,
    block: true,
  },
  dashboard: {
    icon: SquaresFourIcon,
    kindLabel: "Dashboard",
    source: "Product analytics",
    webPath: (id) => `/dashboard/${id}`,
  },
  error: {
    icon: BugIcon,
    kindLabel: "Error issue",
    source: "Error tracking",
    webPath: (id) => `/error_tracking/${id}`,
  },
  replay: {
    icon: PlayCircleIcon,
    kindLabel: "Session replay",
    source: "Session replay",
    webPath: (id) => `/replay/${id}`,
    block: true,
  },
  flag: {
    icon: FlagIcon,
    kindLabel: "Feature flag",
    source: "Feature flags",
    // Flag pages only resolve by numeric id, so a flag cited by key gets no
    // direct URL (its hover preview still resolves through the list search).
    webPath: (id, raw) => (/^\d+$/.test(raw) ? `/feature_flags/${id}` : null),
  },
  experiment: {
    icon: FlaskIcon,
    kindLabel: "Experiment",
    source: "Experiments",
    webPath: (id) => `/experiments/${id}`,
  },
  survey: {
    icon: ClipboardTextIcon,
    kindLabel: "Survey",
    source: "Surveys",
    webPath: (id) => `/surveys/${id}`,
  },
  ticket: {
    icon: ChatCircleTextIcon,
    kindLabel: "Support tickets",
    source: "Conversations",
    webPath: (id) => `/support/tickets/${id}`,
  },
  trace: {
    icon: SparkleIcon,
    kindLabel: "LLM trace",
    source: "AI observability",
    webPath: (id) => `/ai-observability/traces/${id}`,
  },
  eval: {
    icon: ShieldCheckIcon,
    kindLabel: "Evaluation",
    source: "AI evals",
    webPath: (id) => `/ai-evals/evaluations/${id}`,
  },
  event: {
    icon: LightningIcon,
    kindLabel: "Events",
    source: "Product analytics",
    // Cited by name; the page needs the definition id, which the hover
    // preview resolves (resolvedId) before the card can link out.
    webPath: (id, raw) =>
      /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(raw)
        ? `/data-management/events/${id}`
        : null,
  },
  cohort: {
    icon: UsersThreeIcon,
    kindLabel: "Cohort",
    source: "Product analytics",
    webPath: (id) => `/cohorts/${id}`,
  },
  action: {
    icon: CursorClickIcon,
    kindLabel: "Action",
    source: "Product analytics",
    webPath: (id) => `/data-management/actions/${id}`,
  },
  person: {
    icon: UserIcon,
    kindLabel: "Person",
    source: "Product analytics",
    webPath: (id) => `/persons/${id}`,
  },
};

/** Alternate tag names agents plausibly write, mapped to registry kinds. */
const OBJECT_KIND_ALIASES: Record<string, string> = {
  "session-replay": "replay",
  recording: "replay",
  "feature-flag": "flag",
  sql: "hogql",
};

export const GENERIC_OBJECT_KIND: ObjectKindDef = {
  icon: PulseIcon,
  kindLabel: "Evidence",
  source: "PostHog",
};

/** Registry kind for a tag name, or null when the tag isn't an object tag. */
export function resolveObjectKindName(tag: string): string | null {
  if (OBJECT_KINDS[tag]) return tag;
  const alias = OBJECT_KIND_ALIASES[tag];
  return alias && OBJECT_KINDS[alias] ? alias : null;
}

export function getObjectKind(kind: string): ObjectKindDef {
  return OBJECT_KINDS[kind] ?? GENERIC_OBJECT_KIND;
}
