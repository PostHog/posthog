import type { ReactNode } from "react";

/**
 * The uppercase muted heading used for every grouping in Support — sidebar
 * cards, the queue's column header row, menu sections. One component so the
 * heading treatment stays identical across them.
 */
export function SectionLabel({
  size = "sm",
  className = "",
  children,
}: {
  /** `sm` for card chrome, `xs` for dense in-list headings. */
  size?: "sm" | "xs";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`font-semibold text-muted-foreground uppercase tracking-wide ${
        size === "xs" ? "text-[10px]" : "text-[11px]"
      } ${className}`}
    >
      {children}
    </div>
  );
}
