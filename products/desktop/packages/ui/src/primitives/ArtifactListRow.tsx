import { cn } from "@posthog/quill";
import { cardOpenProps } from "@posthog/ui/primitives/ArtifactCard";
import type { ReactNode } from "react";

export function ArtifactListRow({
  icon,
  title,
  meta,
  badges,
  actions,
  onOpen,
  onHoverStart,
}: {
  icon: ReactNode;
  title: string;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  onOpen?: () => void;
  onHoverStart?: () => void;
}) {
  const body = (
    <>
      <span className="flex size-4 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="min-w-0 flex-[1_0_40%] truncate text-foreground">
        {title}
      </span>
      {badges && (
        <span className="flex shrink-0 items-center gap-1 empty:hidden">
          {badges}
        </span>
      )}
      {meta && (
        <span className="flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap text-muted-foreground tabular-nums">
          {typeof meta === "string" ? (
            <span className="truncate">{meta}</span>
          ) : (
            meta
          )}
        </span>
      )}
      {actions && (
        <span className="flex w-0 shrink-0 items-center gap-0.5 overflow-hidden group-focus-within:w-auto group-hover:w-auto">
          {actions}
        </span>
      )}
    </>
  );

  const baseClass =
    "group flex h-7 w-full items-center gap-2 rounded-md px-2 text-xs";

  if (!onOpen) {
    return (
      <div data-artifact-card className={baseClass}>
        {body}
      </div>
    );
  }

  return (
    <div
      data-artifact-card
      className={cn(
        baseClass,
        "cursor-pointer outline-none hover:bg-gray-3 focus-visible:bg-gray-3",
      )}
      {...cardOpenProps(title, onOpen, onHoverStart)}
    >
      {body}
    </div>
  );
}
