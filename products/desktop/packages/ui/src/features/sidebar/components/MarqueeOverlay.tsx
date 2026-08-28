import type { MarqueeRect } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import type { ReactElement } from "react";

/**
 * The band a drag-selection sweeps. Spans the list's full width because the
 * marquee only measures vertically — see `rowsInMarquee`.
 */
export function MarqueeOverlay({
  rect,
}: {
  rect: MarqueeRect | null;
}): ReactElement | null {
  if (!rect) return null;
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 z-10 border-(--accent-8) border-y bg-(--accent-a4)"
      style={{ top: rect.top, height: rect.height }}
    />
  );
}
