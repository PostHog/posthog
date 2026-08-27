const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const FRAME_INTERVAL_MS = 80;

interface DotsCircleSpinnerProps {
  size?: number;
  className?: string;
}

/** Spins via the `ph-dots-frame` CSS animation (globals.css): all frames are
 *  stacked in one grid cell and staggered delays reveal one at a time. Renders
 *  once and never updates, so an always-visible spinner costs no JS. */
export function DotsCircleSpinner({
  size = 12,
  className,
}: DotsCircleSpinnerProps) {
  return (
    <span
      className={`inline-grid place-items-center ${className}`}
      style={{
        width: size,
        height: size,
        fontSize: size,
        lineHeight: 1,
      }}
    >
      {FRAMES.map((frame, index) => (
        <span
          key={frame}
          className="ph-dots-frame"
          style={{ animationDelay: `${index * FRAME_INTERVAL_MS}ms` }}
        >
          {frame}
        </span>
      ))}
    </span>
  );
}
