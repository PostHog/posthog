import { useMemo } from "react";
import { useThemeStore } from "../shell/themeStore";
import { highlightSyntax } from "../utils/syntax-highlight";

interface HighlightedCodeProps {
  code: string;
  language: string;
  className?: string;
}

export function HighlightedCode({
  code,
  language,
  className,
}: HighlightedCodeProps) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const segments = useMemo(
    () => highlightSyntax(code, language, isDarkMode),
    [code, language, isDarkMode],
  );

  if (!segments) {
    return <code className={className}>{code}</code>;
  }

  return (
    <code className={className}>
      {segments.map((segment, i) =>
        segment.color ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable parse output, never reorders
          <span key={i} style={{ color: segment.color }}>
            {segment.text}
          </span>
        ) : (
          segment.text
        ),
      )}
    </code>
  );
}
