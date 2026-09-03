import type { ReactNode } from "react";

/**
 * A label column and a value column, so a reader scanning several of these
 * finds each fact in the same place every time. Children are label/value pairs
 * in source order.
 *
 * `max-content` on the label column: `auto` leaves a gutter the widest label
 * doesn't fill, which reads as two columns that failed to line up.
 */
export function FactList({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-[max-content_minmax(0,1fr)] items-center gap-x-3 gap-y-px text-gray-12 text-xs">
      {children}
    </div>
  );
}

/** A fact's name, a step lighter than its value so the eye lands on answers. */
export function FactLabel({ children }: { children: ReactNode }) {
  return <span className="text-gray-10">{children}</span>;
}
