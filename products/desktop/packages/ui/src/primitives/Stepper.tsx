import { Check } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";

interface StepperProps {
  labels: readonly string[];
  current: number;
  /** Per-step gate: a step is reachable once every step before it is complete. */
  complete: readonly boolean[];
  onSelect: (step: number) => void;
}

/**
 * Numbered step rail for a multi-step form. A step can be revisited once
 * reached, and skipped ahead to only when everything between is complete.
 */
export function Stepper({ labels, current, complete, onSelect }: StepperProps) {
  return (
    <div className="flex w-full min-w-0 flex-col items-stretch">
      {labels.map((label, index) => {
        const isCurrent = index === current;
        const isDone = index < current && complete[index] === true;
        const canSelect =
          index <= current || complete.slice(current, index).every(Boolean);
        return (
          <div key={label} className="flex min-w-0 flex-col items-stretch">
            <button
              type="button"
              disabled={!canSelect}
              aria-current={isCurrent ? "step" : undefined}
              onClick={() => {
                if (canSelect) onSelect(index);
              }}
              className="flex min-w-0 cursor-pointer items-center gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span
                className={`flex size-5 shrink-0 items-center justify-center rounded-full border font-medium text-[11px] ${
                  isCurrent
                    ? "border-(--accent-9) bg-(--accent-9) text-(--accent-contrast)"
                    : isDone
                      ? "border-(--accent-7) bg-(--accent-3) text-(--accent-11)"
                      : "border-(--gray-7) text-(--gray-11)"
                }`}
              >
                {isDone ? <Check size={12} weight="bold" /> : index + 1}
              </span>
              <Text
                className={`truncate text-[12.5px] ${
                  isCurrent
                    ? "font-medium text-(--gray-12)"
                    : "text-(--gray-11)"
                }`}
              >
                {label}
              </Text>
            </button>
            {index < labels.length - 1 && (
              <span className="my-1 ml-2.5 h-4 w-px shrink-0 bg-(--gray-5)" />
            )}
          </div>
        );
      })}
    </div>
  );
}
