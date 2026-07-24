import { useId } from "react";

const DOT_FILL = "var(--gray-6)";

interface DotPatternBackgroundProps {
  className?: string;
  style?: React.CSSProperties;
}

export function DotPatternBackground({
  className,
  style,
}: DotPatternBackgroundProps) {
  const patternId = useId();

  return (
    <svg
      aria-hidden="true"
      style={{
        maskImage: "linear-gradient(to top, black 0%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(to top, black 0%, transparent 100%)",
        ...style,
      }}
      className={`pointer-events-none absolute bottom-0 left-0 h-full w-full opacity-40 ${className ?? ""}`}
    >
      <defs>
        <pattern
          id={patternId}
          patternUnits="userSpaceOnUse"
          width="8"
          height="8"
        >
          <circle cx="0" cy="0" r="1" fill={DOT_FILL} />
          <circle cx="0" cy="8" r="1" fill={DOT_FILL} />
          <circle cx="8" cy="8" r="1" fill={DOT_FILL} />
          <circle cx="8" cy="0" r="1" fill={DOT_FILL} />
          <circle cx="4" cy="4" r="1" fill={DOT_FILL} />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}
