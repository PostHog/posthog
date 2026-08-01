import { Kbd } from "@posthog/quill";
import type React from "react";

interface KeyHintProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function KeyHint({ children, className, style }: KeyHintProps) {
  return (
    <Kbd
      className={`inline-flex items-center text-(--gray-11) text-[11px] ${className ?? ""}`}
      style={{
        fontFamily: "inherit",
        ...style,
      }}
    >
      {children as string}
    </Kbd>
  );
}
