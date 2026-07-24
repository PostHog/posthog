import type { Icon } from "@phosphor-icons/react";
import type { ExecutionMode } from "@posthog/shared/domain-types";
import { Flex, Text } from "@radix-ui/themes";

export interface SuggestedPrompt {
  label: string;
  description: string;
  prompt: string;
  icon: Icon;
  color: string;
  /** Task mode to apply when this suggestion is selected, if it implies one. */
  mode?: ExecutionMode;
}

export interface SuggestedPromptCardProps {
  suggestion: SuggestedPrompt;
  onSelect: () => void;
}

// A starter-prompt card for the channels new-task screen. Mirrors the look of
// SuggestedTaskCard (icon badge + title + description), but clicking it fills
// the composer instead of opening a detail dialog.
export function SuggestedPromptCard({
  suggestion,
  onSelect,
}: SuggestedPromptCardProps) {
  const PromptIcon = suggestion.icon;

  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-(--gray-a3) bg-(--color-panel-solid) px-2.5 py-2 text-left shadow-[0_1px_3px_rgba(0,0,0,0.04),0_1px_2px_rgba(0,0,0,0.02)] transition-[border-color,box-shadow] hover:border-(--card-hover-border) hover:shadow-[0_2px_8px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)]"
      style={
        {
          "--card-hover-border": `var(--${suggestion.color}-6)`,
        } as React.CSSProperties
      }
    >
      <Flex
        align="center"
        justify="center"
        className="h-6 w-6 shrink-0 rounded-md"
        style={{ backgroundColor: `var(--${suggestion.color}-3)` }}
      >
        <PromptIcon
          size={14}
          weight="duotone"
          color={`var(--${suggestion.color}-9)`}
        />
      </Flex>
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Text
          size="1"
          weight="medium"
          className="min-w-0 truncate text-(--gray-12)"
        >
          {suggestion.label}
        </Text>
        <Text size="1" className="line-clamp-1 text-(--gray-11) leading-normal">
          {suggestion.description}
        </Text>
      </Flex>
    </button>
  );
}
