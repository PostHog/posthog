import { compactHomePath } from "@posthog/shared";
import { Box, Checkbox, Flex, Radio, Text } from "@radix-ui/themes";
import { isCancelOption, isOtherOption, isSubmitOption } from "./constants";
import { InlineEditableText } from "./InlineEditableText";
import type { SelectorOption } from "./types";

function needsCustomInput(option: SelectorOption): boolean {
  return option.customInput === true || isOtherOption(option.id);
}

function getPlaceholder(
  option: SelectorOption,
  customInputPlaceholder: string,
): string {
  if (option.customInput) {
    return "Type here to tell the agent what to do differently";
  }
  return customInputPlaceholder;
}

interface OptionRowProps {
  option: SelectorOption;
  index: number;
  isSelected: boolean;
  isHovered: boolean;
  isChecked: boolean;
  showCheckbox: boolean;
  multiSelect: boolean;
  customInput: string;
  customInputPlaceholder: string;
  isEditing: boolean;
  submitLabel: string;
  disabled?: boolean;
  onCustomInputChange: (value: string) => void;
  onNavigateUp: () => void;
  onNavigateDown: () => void;
  onEscape: () => void;
  onInlineSubmit: () => void;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function OptionRow({
  option,
  index,
  isSelected,
  isHovered,
  isChecked,
  showCheckbox,
  multiSelect,
  customInput,
  customInputPlaceholder,
  isEditing,
  submitLabel,
  disabled = false,
  onCustomInputChange,
  onNavigateUp,
  onNavigateDown,
  onEscape,
  onInlineSubmit,
  onClick,
  onMouseEnter,
  onMouseLeave,
}: OptionRowProps) {
  if (isSubmitOption(option.id) || isCancelOption(option.id)) {
    const isCancel = isCancelOption(option.id);
    const submitBg = disabled
      ? "bg-(--gray-4)"
      : isSelected
        ? "bg-(--blue-8)"
        : isHovered
          ? "bg-(--blue-4)"
          : "bg-(--blue-3)";
    return (
      <Flex
        align="center"
        justify="center"
        gap="2"
        onClick={disabled ? undefined : onClick}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        px="2"
        className={`inline-flex h-[28px] rounded-(--radius-2) ${
          disabled ? "cursor-not-allowed" : "cursor-pointer"
        } ${
          isCancel ? (isSelected ? "bg-(--gray-6)" : "bg-(--gray-3)") : submitBg
        }`}
      >
        <Text
          className={`font-medium text-[13px] ${
            disabled
              ? "text-gray-9"
              : isSelected
                ? isCancel
                  ? "text-gray-12"
                  : "text-blue-12"
                : "text-gray-12"
          }`}
        >
          {isCancel ? option.label : submitLabel}
        </Text>
      </Flex>
    );
  }

  const showsCustomInput = needsCustomInput(option);
  const isCurrentlyEditing = isEditing && isSelected;

  const renderLabel = () => {
    if (showsCustomInput) {
      return (
        <InlineEditableText
          value={customInput}
          placeholder={getPlaceholder(option, customInputPlaceholder)}
          active={isCurrentlyEditing}
          onChange={onCustomInputChange}
          onNavigateUp={onNavigateUp}
          onNavigateDown={onNavigateDown}
          onEscape={onEscape}
          onSubmit={onInlineSubmit}
        />
      );
    }

    const displayText = compactHomePath(option.label);
    const textClass = isSelected
      ? "text-primary"
      : isHovered
        ? "text-primary"
        : "text-gray-12";

    return (
      <Text
        className={`whitespace-pre-wrap font-medium text-[13px] leading-4 ${textClass}`}
      >
        {displayText}
      </Text>
    );
  };

  return (
    <Box
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      py="1"
      className={`-mx-3 cursor-pointer select-none rounded-(--radius-2) pt-[4px] pr-3 pb-[4px] pl-3 ${
        isSelected
          ? "bg-primary/10"
          : isHovered
            ? "bg-fill-hover"
            : "bg-transparent"
      }`}
    >
      <Flex align="center" gap="2" className="leading-4">
        <Text
          className={`w-[1ch] shrink-0 text-[13px] leading-4 ${isSelected ? "text-primary" : "text-gray-11"}`}
        >
          {isSelected ? "›" : ""}
        </Text>
        <Text
          className={`min-w-[16px] shrink-0 whitespace-nowrap text-right text-[13px] leading-4 ${
            isSelected
              ? "text-primary"
              : isHovered
                ? "text-primary"
                : "text-gray-11"
          }`}
        >
          {index + 1}.
        </Text>
        {showCheckbox &&
          (multiSelect ? (
            <Checkbox
              size="1"
              color="green"
              checked={isChecked}
              className="pointer-events-none shrink-0"
            />
          ) : (
            <Radio
              size="1"
              color="green"
              value={option.id}
              checked={isChecked}
              className="pointer-events-none shrink-0"
            />
          ))}
        <Box className="min-w-0 flex-1 leading-4">{renderLabel()}</Box>
      </Flex>
      {option.description && !isCurrentlyEditing && (
        <Text
          as="p"
          className={`mt-[2px] text-[13px] text-gray-11 ${showCheckbox ? "ml-[64px]" : "ml-[40px]"}`}
        >
          {compactHomePath(option.description)}
        </Text>
      )}
    </Box>
  );
}
