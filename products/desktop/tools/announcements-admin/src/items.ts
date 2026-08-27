import type { Announcement } from "@posthog/shared/announcements";

export interface EditableItem {
  kind: "announcement" | "required-update";
  id: string;
  title: string;
  body: string;
  startsAt: string;
  endsAt: string;
  style: "banner" | "modal";
  minVersion: string;
  ctaLabel: string;
  ctaUrl: string;
  requiresAck: boolean;
  ackLabel: string;
  heroType: "hedgehog" | "image" | "none";
  /** A bundled hedgehog name or any PostHog/brand hoggie slug. */
  heroHedgehog: string;
  heroColor: string;
  heroImageUrl: string;
}

/** What the app renders when the payload carries no hero field. */
export function kindDefaultHedgehog(
  kind: EditableItem["kind"],
): EditableItem["heroHedgehog"] {
  return kind === "required-update" ? "builder" : "happy";
}

export function blankItem(kind: EditableItem["kind"]): EditableItem {
  return {
    kind,
    id: "",
    title: "",
    body: "",
    startsAt: "",
    endsAt: "",
    style: "banner",
    minVersion: "",
    ctaLabel: "",
    ctaUrl: "",
    requiresAck: false,
    ackLabel: "",
    heroType: "hedgehog",
    heroHedgehog: kindDefaultHedgehog(kind),
    heroColor: "",
    heroImageUrl: "",
  };
}

/**
 * Dismissals persist per id on every client forever, so an id must never be
 * reused across the payload's whole history — deduping against the current
 * items (as a date-stamped scheme would) still collides with ids that were
 * published and since removed. UUIDs make reuse impossible; the field stays
 * editable for anyone who wants a semantic id instead.
 */
export function newItemId(): string {
  return crypto.randomUUID();
}

export function toEditable(items: Announcement[]): EditableItem[] {
  return items.map((item) => ({
    ...blankItem(item.kind),
    id: item.id,
    title: item.title,
    body: item.body,
    startsAt: item.startsAt ?? "",
    endsAt: item.endsAt ?? "",
    style: item.kind === "announcement" ? item.style : "banner",
    minVersion: item.minVersion ?? "",
    ctaLabel: item.kind === "announcement" ? (item.cta?.label ?? "") : "",
    ctaUrl: item.kind === "announcement" ? (item.cta?.url ?? "") : "",
    requiresAck: item.kind === "announcement" ? item.requiresAck : false,
    ackLabel: item.kind === "announcement" ? (item.ackLabel ?? "") : "",
    heroType:
      item.hero && "none" in item.hero
        ? ("none" as const)
        : item.hero && "imageUrl" in item.hero
          ? ("image" as const)
          : ("hedgehog" as const),
    heroHedgehog:
      item.hero && "hedgehog" in item.hero
        ? item.hero.hedgehog
        : kindDefaultHedgehog(item.kind),
    heroColor:
      item.hero && "hedgehog" in item.hero ? (item.hero.color ?? "") : "",
    heroImageUrl:
      item.hero && "imageUrl" in item.hero ? item.hero.imageUrl : "",
  }));
}

export function toPayloadItem(item: EditableItem): Record<string, unknown> {
  const base: Record<string, unknown> = {
    kind: item.kind,
    id: item.id,
    title: item.title,
    body: item.body,
  };
  if (item.startsAt) base.startsAt = item.startsAt;
  if (item.endsAt) base.endsAt = item.endsAt;

  // Heroes only render on modals, and the app already shows the kind-default
  // hedgehog when the field is absent — emit hero only when it changes that.
  const rendersModal =
    item.kind === "required-update" || item.style === "modal";
  if (rendersModal) {
    if (item.heroType === "none") {
      base.hero = { none: true };
    } else if (item.heroType === "image") {
      base.hero = { imageUrl: item.heroImageUrl };
    } else if (
      item.heroColor ||
      item.heroHedgehog !== kindDefaultHedgehog(item.kind)
    ) {
      base.hero = {
        hedgehog: item.heroHedgehog,
        ...(item.heroColor ? { color: item.heroColor } : {}),
      };
    }
  }

  if (item.kind === "required-update") {
    base.minVersion = item.minVersion;
    return base;
  }
  base.style = item.style;
  if (item.minVersion) base.minVersion = item.minVersion;
  if (item.requiresAck) {
    base.requiresAck = true;
    if (item.ackLabel) base.ackLabel = item.ackLabel;
  } else if (item.ctaLabel || item.ctaUrl) {
    base.cta = { label: item.ctaLabel, url: item.ctaUrl };
  }
  return base;
}

export function isoToLocalInput(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function localInputToIso(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}
