import { useId } from "react";

const GRID_STROKE = "var(--border)";

export function MathGridBackground() {
  const patternId = useId();

  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 size-full opacity-[0.35] dark:opacity-[0.16]"
      style={{
        maskImage:
          "radial-gradient(circle at center, black 0%, rgba(0, 0, 0, 0.72) 48%, transparent 88%)",
        WebkitMaskImage:
          "radial-gradient(circle at center, black 0%, rgba(0, 0, 0, 0.72) 48%, transparent 88%)",
      }}
    >
      <defs>
        <pattern
          id={patternId}
          width="32"
          height="32"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M 32 0 L 0 0 0 32"
            fill="none"
            stroke={GRID_STROKE}
            strokeWidth="0.5"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}
