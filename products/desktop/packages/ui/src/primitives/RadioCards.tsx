import { Radio } from "@base-ui/react/radio";
import {
  ItemContent,
  ItemDescription,
  ItemTitle,
  RadioGroup,
  RadioIndicator,
} from "@posthog/quill";

export interface RadioCardOption<T extends string> {
  value: T;
  title: string;
  description: string;
  disabled?: boolean;
}

interface RadioCardsProps<T extends string> {
  value: T;
  options: readonly RadioCardOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  /** Kebab-case prefix for each card's data-attr. */
  dataAttrPrefix?: string;
}

/**
 * A choice between a few options where each one needs a sentence to explain
 * it. The card is the radio itself rather than a label pointing at one, so the
 * whole card is the control: it takes focus, answers the arrow keys through the
 * group, and reports its own checked state.
 *
 * Built on Base UI's radio rather than quill's RadioGroupItem, which supplies
 * its own children and so cannot hold a card's content.
 */
export function RadioCards<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  dataAttrPrefix,
}: RadioCardsProps<T>) {
  return (
    <RadioGroup
      aria-label={ariaLabel}
      value={value}
      onValueChange={(next) => onChange(next as T)}
      className={`grid gap-2 ${options.length === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Radio.Root
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            data-attr={
              dataAttrPrefix ? `${dataAttrPrefix}-${option.value}` : undefined
            }
            className={`flex h-auto w-full items-start gap-3 rounded-(--radius-3) border border-(--gray-6) bg-transparent px-3 py-2.5 text-left transition-colors motion-reduce:transition-none ${
              option.disabled
                ? "opacity-55"
                : "cursor-pointer hover:border-(--gray-8)"
            } ${selected ? "border-(--accent-9) shadow-[0_0_0_1px_var(--accent-9)]" : ""}`}
          >
            <ItemContent>
              <ItemTitle className="text-[12.5px]">{option.title}</ItemTitle>
              <ItemDescription className="text-[11.5px] leading-snug">
                {option.description}
              </ItemDescription>
            </ItemContent>
            <RadioIndicator checked={selected} className="mt-0.5 shrink-0" />
          </Radio.Root>
        );
      })}
    </RadioGroup>
  );
}
