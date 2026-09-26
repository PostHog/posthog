import { cn } from "@posthog/quill";
import { useNavRailMetrics } from "@posthog/ui/features/sidebar/navRailSize";
import type { ComponentPropsWithRef, ReactNode } from "react";

interface NavRailTileProps extends ComponentPropsWithRef<"button"> {
  children: ReactNode;
  caption: string;
  tileClassName?: string;
}

export function NavRailTile({
  children,
  caption,
  tileClassName,
  className,
  ref,
  ...buttonProps
}: NavRailTileProps) {
  const metrics = useNavRailMetrics();
  return (
    <button
      {...buttonProps}
      ref={ref}
      type="button"
      className={cn(
        "group flex w-full shrink-0 cursor-pointer flex-col items-center gap-0.5 text-muted-foreground outline-none hover:text-foreground aria-expanded:text-foreground data-selected:text-foreground",
        className,
      )}
    >
      <span
        className={cn(
          "relative flex items-center justify-center rounded-md group-hover:bg-fill-hover group-focus-visible:ring-2 group-focus-visible:ring-ring group-aria-expanded:bg-fill-selected group-data-selected:bg-fill-selected",
          metrics.tileClassName,
          tileClassName,
        )}
      >
        {children}
      </span>
      {metrics.captionClassName && (
        <span
          aria-hidden
          className={cn("max-w-full truncate px-0.5", metrics.captionClassName)}
        >
          {caption}
        </span>
      )}
    </button>
  );
}
