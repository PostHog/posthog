import { Flex, Button as RadixButton, Text } from "@radix-ui/themes";
import {
  type ComponentPropsWithoutRef,
  forwardRef,
  type ReactNode,
} from "react";
import { Tooltip } from "./Tooltip";

export type ButtonProps = ComponentPropsWithoutRef<typeof RadixButton> & {
  /** Primary tooltip explaining what the button does. */
  tooltipContent?: ReactNode;
  /**
   * When non-null and the button is disabled, shown after "Disabled because" in the tooltip.
   * Must be null when the action is allowed.
   */
  disabledReason?: string | null;
};

function disabledBecauseLabel(detail: string): string {
  const d = detail.trim().replace(/\.$/, "");
  return `Disabled because ${d}.`;
}

function buildTooltipContent(
  tooltipContent: ReactNode | undefined,
  disabledReason: string | null | undefined,
  disabled: boolean | undefined,
): ReactNode | undefined {
  const reason = disabled ? disabledReason : null;
  if (tooltipContent != null && reason) {
    return (
      <Flex direction="column" gap="2" className="max-w-[280px]">
        <Text as="span" className="text-(--gray-12) text-[13px]">
          {tooltipContent}
        </Text>
        <Text as="span" color="gray" className="text-[13px] leading-[1.45]">
          {disabledBecauseLabel(reason)}
        </Text>
      </Flex>
    );
  }
  if (reason) {
    return disabledBecauseLabel(reason);
  }
  if (tooltipContent != null) {
    return tooltipContent;
  }
  return undefined;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ tooltipContent, disabledReason, disabled, ...props }, ref) {
    const tip = buildTooltipContent(
      tooltipContent,
      disabledReason ?? null,
      disabled,
    );

    const button = <RadixButton ref={ref} disabled={disabled} {...props} />;

    if (tip === undefined) {
      return button;
    }

    // Disabled buttons don't receive pointer events; span keeps the tooltip hover target.
    const trigger =
      disabled === true ? (
        <span className="inline-flex cursor-not-allowed">{button}</span>
      ) : (
        button
      );

    return <Tooltip content={tip}>{trigger}</Tooltip>;
  },
);

Button.displayName = "Button";
