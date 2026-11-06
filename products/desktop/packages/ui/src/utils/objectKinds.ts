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
  TrayIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import {
  FALLBACK_OBJECT_KIND_DATA,
  OBJECT_KIND_DATA,
  type ObjectKindData,
  type ObjectKindName,
} from "@posthog/core/inbox/objectKinds.generated";
import { objectKindMeta } from "@posthog/core/inbox/objectTags";

/**
 * The registry of PostHog object kinds an agent can embed in a message as
 * `<kind id="...">label</kind>` tags (see remarkObjectTags), read from the
 * generated registry (source of truth: posthog/object_tags/kinds.py).
 *
 * Adding a kind there is all it takes for the inline chip: labels and the
 * click-through URL come from the registry, and the `Record<ObjectKindName>`
 * icon map below fails typecheck until the new kind gets an icon. Two opt-ins
 * live elsewhere:
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

const KIND_ICONS: Record<ObjectKindName, Icon> = {
  insight: ChartLineIcon,
  hogql: DatabaseIcon,
  dashboard: SquaresFourIcon,
  error: BugIcon,
  replay: PlayCircleIcon,
  flag: FlagIcon,
  experiment: FlaskIcon,
  survey: ClipboardTextIcon,
  ticket: ChatCircleTextIcon,
  report: TrayIcon,
  trace: SparkleIcon,
  eval: ShieldCheckIcon,
  event: LightningIcon,
  cohort: UsersThreeIcon,
  action: CursorClickIcon,
  person: UserIcon,
};

function toDef(data: ObjectKindData, icon: Icon): ObjectKindDef {
  const def: ObjectKindDef = { icon, ...objectKindMeta(data) };
  if (data.block) {
    def.block = true;
  }
  return def;
}

const OBJECT_KINDS: Record<string, ObjectKindDef> = Object.fromEntries(
  (Object.entries(OBJECT_KIND_DATA) as [ObjectKindName, ObjectKindData][]).map(
    ([name, data]) => [name, toDef(data, KIND_ICONS[name])],
  ),
);

const GENERIC_OBJECT_KIND: ObjectKindDef = toDef(
  FALLBACK_OBJECT_KIND_DATA,
  PulseIcon,
);

export { resolveObjectKindName } from "@posthog/core/inbox/objectTags";

export function getObjectKind(kind: string): ObjectKindDef {
  return OBJECT_KINDS[kind] ?? GENERIC_OBJECT_KIND;
}
