import { cn } from "@posthog/quill";

// Must match the `ph-dot-ring` animation duration in styles/globals.css: the
// keyframe lives in CSS (so the spinner costs no JS timers) while the per-dot
// stagger is computed here, and the two only read as one ring if they agree.
const RING_DURATION_MS = 900;

// The eight perimeter cells of a 3x3 grid, clockwise from the top, as
// [row, column]. The centre stays empty — that hole is what makes the ring read
// as a circle rather than a block of dots.
const RING_CELLS = [
  [1, 2],
  [1, 3],
  [2, 3],
  [3, 3],
  [3, 2],
  [3, 1],
  [2, 1],
  [1, 1],
] as const;

/**
 * A circular dots spinner: eight dots on a 3x3 ring with a highlight travelling
 * around it. Drawn from real elements rather than braille glyphs
 * (`DotsCircleSpinner`), which buys three things at nav-row size: the ring is
 * actually round instead of a 2x4 cell, it scales cleanly because the dots are
 * sized in px rather than by font metrics, and it can't be reshaped by whatever
 * font a host happens to resolve for U+28xx.
 *
 * Colour comes from `currentColor`, so the caller sets the tone.
 */
export function DotRingSpinner({
  size = 12,
  className,
}: {
  size?: number;
  className?: string;
}) {
  // A fifth of the box leaves roughly a dot's worth of gap between neighbours.
  // Deliberately NOT rounded to whole pixels: the ring has to fit the same box
  // as a plain status dot, and at that size rounding is the difference between
  // eight dots and a smudge. Fractional sizes are fine — they land on device
  // pixels on any 2x display, and border-radius keeps them round below that.
  const dot = size / 5;
  return (
    <span
      aria-hidden="true"
      className={cn("grid shrink-0", className)}
      style={{
        width: size,
        height: size,
        gridTemplateColumns: "repeat(3, 1fr)",
        gridTemplateRows: "repeat(3, 1fr)",
      }}
    >
      {RING_CELLS.map(([row, column], index) => (
        <span
          key={`${row}-${column}`}
          className="ph-dot-ring place-self-center rounded-full bg-current"
          style={{
            width: dot,
            height: dot,
            gridRow: row,
            gridColumn: column,
            animationDelay: `${(index * RING_DURATION_MS) / RING_CELLS.length}ms`,
          }}
        />
      ))}
    </span>
  );
}
