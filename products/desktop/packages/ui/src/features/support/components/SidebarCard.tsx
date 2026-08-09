import type { ReactNode } from "react";
import { SectionLabel } from "./SectionLabel";

/**
 * Shared chrome for the ticket sidebar's cards. Always expanded — a card with
 * nothing to show returns null rather than collapsing, so the column never
 * reads as "there might be something behind this chevron".
 */
export function SidebarCard({
  title,
  icon,
  trailing,
  children,
}: {
  title: string;
  icon?: ReactNode;
  /** Small element right of the title, e.g. a count. */
  trailing?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded border border-border bg-card p-3">
      <SectionLabel className="mb-2 flex items-center gap-2">
        {icon && <span className="shrink-0">{icon}</span>}
        <span>{title}</span>
        {trailing && <span className="ml-auto">{trailing}</span>}
      </SectionLabel>
      {children}
    </div>
  );
}

/** One-line state inside a card. For a whole empty region use quill's `Empty`. */
export function StateLine({
  kind,
  children,
}: {
  kind: "loading" | "empty" | "error";
  children: ReactNode;
}) {
  return (
    <div
      className={`text-[11px] ${
        kind === "error" ? "text-destructive" : "text-muted-foreground"
      }`}
    >
      {children}
    </div>
  );
}

/** Label-left / value-right row. Renders nothing when the value is empty, so
 *  cards with conditional fields don't leave gaps. */
export function CardRow({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-baseline justify-between gap-2 text-[12px]">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right text-foreground">
        {value}
      </span>
    </div>
  );
}

/** Same shape as `CardRow` but centred, so a picker pill sits flush with its label. */
export function CardPickerRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-[12px]">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
