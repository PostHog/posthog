import { PencilSimple } from "@phosphor-icons/react";
import { parseSpendAmount } from "@posthog/core/billing/spendLimits";
import { useRef, useState } from "react";

interface SpendKnobValueProps {
  valueUsd: number;
  /** The amount as displayed, e.g. "$1,000". */
  label: string;
  /** Accessible name, since the amount alone does not say which line it is. */
  name: string;
  onCommit: (value: number) => void;
}

/** Shared by the input and the hidden sizer, so the two measure identically. */
const BOX =
  "rounded-(--radius-2) border px-2 py-1 pr-6 font-medium text-[12px] tabular-nums leading-none";

/**
 * A knob's amount, in a callout above the knob.
 *
 * It is always the same input element: clicking focuses it rather than
 * swapping it for something else, so nothing moves. Width comes from a hidden
 * copy of the text behind it, so the callout fits its value without the
 * element itself having to resize on focus.
 */
export function SpendKnobValue({
  valueUsd,
  label,
  name,
  onCommit,
}: SpendKnobValueProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(label);
  // Escape blurs the input to end the edit, but blur() dispatches focusout
  // synchronously, so onBlur's commit runs before the setDraft(label) it
  // queues re-renders. A ref, read at commit time, tells commit to discard.
  const cancelEdit = useRef(false);

  // Re-sync while idle, so dragging the knob updates the text without an
  // effect and without clobbering what is being typed.
  if (!editing && draft !== label) setDraft(label);

  const commit = () => {
    setEditing(false);
    if (cancelEdit.current) {
      cancelEdit.current = false;
      setDraft(label);
      return;
    }
    const parsed = parseSpendAmount(draft);
    if (parsed === null) {
      setDraft(label);
      return;
    }
    if (parsed !== valueUsd) onCommit(parsed);
  };

  const border = editing ? "border-(--accent-9)" : "border-(--gray-6)";

  return (
    <span className="relative block">
      {/* Sizer: same text and metrics as the input, so the callout is exactly
          as wide as its value. */}
      <span aria-hidden="true" className={`${BOX} invisible block border`}>
        {draft}
      </span>
      <input
        aria-label={`${name} in dollars. Click to type an amount`}
        inputMode="decimal"
        className={`${BOX} absolute inset-0 cursor-pointer bg-card text-(--gray-12) shadow-sm outline-none focus:cursor-text ${border} ${
          editing ? "" : "hover:border-(--gray-8) hover:bg-(--gray-2)"
        }`}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onFocus={(event) => {
          setEditing(true);
          event.currentTarget.select();
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
            return;
          }
          if (event.key === "Escape") {
            cancelEdit.current = true;
            event.currentTarget.blur();
          }
        }}
      />
      <PencilSimple
        size={10}
        aria-hidden="true"
        className="-translate-y-1/2 pointer-events-none absolute top-1/2 right-1.5 text-(--gray-10)"
      />
      {/* A rotated square borrowing the callout's own fill and border, so the
          callout points at the knob it belongs to. */}
      <span
        aria-hidden="true"
        className={`-bottom-[4px] -translate-x-1/2 absolute left-1/2 size-[7px] rotate-45 border-r border-b bg-card ${border}`}
      />
    </span>
  );
}
