import { cn } from "@posthog/quill";
import { Badge as RadixBadge } from "@radix-ui/themes";
import type { ComponentPropsWithoutRef } from "react";

type RadixBadgeProps = ComponentPropsWithoutRef<typeof RadixBadge>;

export type BadgeProps = RadixBadgeProps;

/**
 * Compact, uppercase badge built on Radix Badge.
 * Applies the house style (`size="1"`, `variant="surface"`, small text, uppercase)
 * so callers only need to pass `color` and children.
 */
export function Badge({
  size = "1",
  variant = "surface",
  className,
  ...props
}: BadgeProps) {
  return (
    <RadixBadge
      size={size}
      variant={variant}
      className={cn(
        "!py-[3px] !px-[5px] !text-[9px] !leading-tight uppercase",
        className,
      )}
      {...props}
    />
  );
}
