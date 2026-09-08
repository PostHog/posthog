import { useId } from "react";

const MINOR_GRID_STROKE = "var(--blue-a4)";
const MAJOR_GRID_STROKE = "var(--blue-a5)";

export function MathGridBackground() {
  const minorPatternId = useId();
  const majorPatternId = useId();

  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 size-full opacity-45 dark:opacity-20"
      style={{
        maskImage:
          "radial-gradient(circle at center, black 0%, rgba(0, 0, 0, 0.72) 48%, transparent 88%)",
        WebkitMaskImage:
          "radial-gradient(circle at center, black 0%, rgba(0, 0, 0, 0.72) 48%, transparent 88%)",
      }}
    >
      <defs>
        <pattern
          id={minorPatternId}
          width="24"
          height="24"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M 24 0 L 0 0 0 24"
            fill="none"
            stroke={MINOR_GRID_STROKE}
            strokeWidth="0.5"
          />
        </pattern>
        <pattern
          id={majorPatternId}
          width="96"
          height="96"
          patternUnits="userSpaceOnUse"
        >
          <rect width="96" height="96" fill={`url(#${minorPatternId})`} />
          <path
            d="M 96 0 L 0 0 0 96"
            fill="none"
            stroke={MAJOR_GRID_STROKE}
            strokeWidth="0.75"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${majorPatternId})`} />
    </svg>
  );
}
