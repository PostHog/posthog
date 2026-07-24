import { Check, Copy } from "@phosphor-icons/react";
import { IconButton } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { useCallback, useState } from "react";

type CodeBlockSize = "1" | "1.5" | "2" | "3";

interface CodeBlockProps {
  children: ReactNode;
  size?: CodeBlockSize;
  showCopy?: boolean;
}

const SIZE_TO_CLASS: Record<CodeBlockSize, string> = {
  "1": "text-[13px]",
  "1.5": "text-[13.5px]",
  "2": "text-sm",
  "3": "text-base",
};

function extractText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (children && typeof children === "object" && "props" in children) {
    const props = (
      children as { props: { children?: ReactNode; code?: string } }
    ).props;
    if (typeof props.code === "string") return props.code;
    return extractText(props.children);
  }
  return "";
}

export function CodeBlock({
  children,
  size = "1",
  showCopy = true,
}: CodeBlockProps) {
  const sizeClass = SIZE_TO_CLASS[size];
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const text = extractText(children);
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [children]);

  return (
    <div className="group relative">
      <pre
        className={`m-0 mb-3 overflow-x-auto whitespace-pre rounded-(--radius-2) border border-(--gray-6) bg-(--gray-3) p-3 pr-10 font-[var(--code-font-family)] text-(--gray-12) ${sizeClass}`}
      >
        {children}
      </pre>
      {showCopy ? (
        <IconButton
          size="1"
          variant="ghost"
          color="gray"
          onClick={handleCopy}
          className="absolute top-1 right-1 cursor-pointer"
          aria-label="Copy code"
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
        </IconButton>
      ) : null}
    </div>
  );
}
