import type { SpendAnalysisWindow } from "@posthog/core/billing/spendAnalysisFormat";
import { SegmentedControl } from "@radix-ui/themes";

const WINDOW_OPTIONS: { value: SpendAnalysisWindow; label: string }[] = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
];

interface WindowSelectorProps {
  value: SpendAnalysisWindow;
  onChange: (window: SpendAnalysisWindow) => void;
}

export function WindowSelector({ value, onChange }: WindowSelectorProps) {
  return (
    <SegmentedControl.Root
      value={value}
      size="1"
      onValueChange={(next) => {
        const found = WINDOW_OPTIONS.find((option) => option.value === next);
        if (found) onChange(found.value);
      }}
      aria-label="Spend analysis window"
    >
      {WINDOW_OPTIONS.map((option) => (
        <SegmentedControl.Item key={option.value} value={option.value}>
          {option.label}
        </SegmentedControl.Item>
      ))}
    </SegmentedControl.Root>
  );
}
