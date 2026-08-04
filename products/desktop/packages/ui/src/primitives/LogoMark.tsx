import { cn } from "@posthog/quill";
import type { CSSProperties } from "react";

// How far apart neighbouring spikes crest. The keyframe (and its duration)
// lives in styles/globals.css as `ph-spike-wave`, so the wave costs no JS
// timers; the stagger here has to stay well inside that duration or the wave
// stops reading as one gesture rolling across the back and becomes spikes
// taking turns at random.
const WAVE_STAGGER_MS = 150;

// The logomark's own geometry, from Logo.tsx. Width / height of the viewBox —
// callers give a width and the height follows, so the mark can never be
// squashed into a different hedgehog.
const VIEWBOX_WIDTH = 51.669;
const VIEWBOX_HEIGHT = 28;

/**
 * The three spikes on the hedgehog's back, tail to head. Each is the union of
 * the gradient slices Logo.tsx draws it with, redrawn as one outline so a
 * single-colour fill can't show hairline seams between slices — and so each
 * spike is one element the wave can move on its own.
 */
const SPIKE_PATHS = [
  // Tail spike (blue in the full-colour mark).
  "M10.7401 7.14295L4.58711 0.815297C2.91642 -0.907781 0 0.279746 0 2.67808V25.4097C0 26.8403 1.15978 28.0001 2.59044 28.0001H10.7401Z",
  // Middle spike (red).
  "M21.9693 7.64927L15.3273 0.815174C13.6567 -0.907902 10.7402 0.279623 10.7402 2.67796V28.0003H21.9693Z",
  // Head-side spike (yellow).
  "M33.2915 7.74241L26.5563 0.815175C24.8857 -0.907902 21.9692 0.279624 21.9692 2.67796V28.0003H33.2915Z",
];

// The head with the eye as a second subpath; `evenodd` is what punches it
// through to the background instead of filling it over.
const HEAD_PATH =
  "M50.01 23.3376L49.6723 23.2968C48.6653 23.1687 47.7281 22.7031 47.0179 21.9696L33.2856 7.74255V28.0003H48.9971C50.4757 28.0003 51.669 26.8012 51.669 25.3284V25.2236C51.669 24.2631 50.953 23.454 50.0041 23.3376H50.01ZM39.2 23.5471C38.2162 23.5471 37.4187 22.7496 37.4187 21.7658C37.4187 20.7821 38.2162 19.9845 39.2 19.9845C40.1838 19.9845 40.9813 20.7821 40.9813 21.7658C40.9813 22.7496 40.1838 23.5471 39.2 23.5471Z";

/**
 * The PostHog logomark as a single-tone glyph, drawn in `currentColor` so the
 * caller sets the tone. With `wave`, the spikes on the hedgehog's back lift and
 * brighten in turn, tail to head — motion that travels, for states where output
 * is arriving.
 */
export function LogoMark({
  width = 15,
  wave = false,
  className,
  style,
}: {
  width?: number;
  wave?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
      width={width}
      height={(width * VIEWBOX_HEIGHT) / VIEWBOX_WIDTH}
      fill="currentColor"
      className={cn("shrink-0", className)}
      style={style}
    >
      {SPIKE_PATHS.map((d, index) => (
        <path
          key={d}
          d={d}
          className={wave ? "ph-spike-wave" : undefined}
          // Negative delays: a positive delay leaves later spikes sitting at
          // their natural full-height, full-opacity state until their first
          // cycle starts — a bright flash on every mount. Starting each spike
          // mid-cycle keeps the stagger and makes the wave already rolling on
          // first paint.
          style={
            wave
              ? {
                  animationDelay: `${(index - SPIKE_PATHS.length) * WAVE_STAGGER_MS}ms`,
                }
              : undefined
          }
        />
      ))}
      <path d={HEAD_PATH} fillRule="evenodd" />
    </svg>
  );
}
