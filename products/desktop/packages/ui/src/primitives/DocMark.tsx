import { cn } from "@posthog/quill";

export type DocMarkVariant = "agent" | "discussion";

/**
 * agent: still | working | waiting | failed. discussion: open | handled. The
 * glyph is the same; the state says whether it moves and what colour it takes.
 */
export type DocMarkState =
  | "still"
  | "working"
  | "waiting"
  | "failed"
  | "open"
  | "handled";

const ARMS = [0, 60, 120, 180, 240, 300];

/**
 * The mark a doc puts beside a line that has a thread: an asterisk with six
 * rounded arms, one colour for every thread. It turns while the agent works,
 * blinks while the agent waits on a person, and goes hollow once handled.
 */
export function DocMark({
  variant,
  state = variant === "agent" ? "still" : "open",
  size = 14,
  count,
  className,
}: {
  variant: DocMarkVariant;
  state?: DocMarkState;
  size?: number;
  /** Replies on the thread, drawn small at the lower right. */
  count?: number;
  className?: string;
}) {
  const hollow = state === "handled";
  return (
    <span
      className={cn("doc-mark", className)}
      data-variant={variant}
      data-state={state}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="doc-mark-glyph"
      >
        <g className="doc-mark-arms">
          {ARMS.map((angle) => (
            <path
              key={angle}
              className="doc-mark-arm"
              d="M8 8 L8 1.6"
              transform={`rotate(${angle} 8 8)`}
              stroke="currentColor"
              strokeWidth={hollow ? 1.4 : 2.3}
              strokeLinecap="round"
            />
          ))}
        </g>
        <circle cx="8" cy="8" r={hollow ? 1.1 : 1.6} fill="currentColor" />
      </svg>
      {count && count > 0 ? (
        <span className="doc-mark-count">{count > 9 ? "9+" : count}</span>
      ) : null}
    </span>
  );
}
