import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { useEffect, useRef, useState } from "react";

/** How long either confirmation stays up before the button goes back. */
const COPIED_MS = 1500;

/**
 * Copy-to-clipboard button with a transient confirmation. Icon-only by default;
 * `bare` drops the border/background so it can nest inside another pill or a
 * line of text.
 *
 * `confirm` picks how it says it worked: the check icon where the button has
 * room to change, or an anchored tooltip where it doesn't — a 14px glyph at the
 * end of a truncated line has nowhere to put a word.
 */
export function CopyButton({
  text,
  label = "Copy",
  showLabel = false,
  bare = false,
  confirm = "icon",
}: {
  text: string;
  label?: string;
  showLabel?: boolean;
  bare?: boolean;
  confirm?: "icon" | "tooltip";
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => (timer.current ? clearTimeout(timer.current) : undefined),
    [],
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      // Clipboard can be blocked (insecure context) — the text stays selectable.
    }
  }

  const showCheck = copied && confirm === "icon";
  const button = (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      className={
        bare
          ? "inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-(--radius-1) px-1 py-0.5 text-gray-10 transition-colors hover:bg-(--gray-4) hover:text-gray-12"
          : "inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-(--radius-1) border border-border bg-(--color-panel-solid) px-1.5 py-0.5 text-[11px] text-gray-11 transition-colors hover:bg-(--gray-3) hover:text-gray-12"
      }
    >
      {showCheck ? (
        <CheckIcon size={12} className="text-(--green-11)" />
      ) : (
        <CopyIcon size={12} />
      )}
      {showLabel ? (showCheck ? "Copied" : label) : null}
    </button>
  );

  if (confirm === "icon") return button;
  return (
    <TooltipProvider delay={200}>
      {/* Held open while it says "Copied!": the confirmation has to survive the
          pointer leaving the button it fired from. */}
      <Tooltip disableHoverablePopup open={copied || undefined}>
        <TooltipTrigger render={button} />
        <TooltipContent side="top" className="pointer-events-none select-none">
          {copied ? "Copied!" : label}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
