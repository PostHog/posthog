import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

/**
 * One artifact card. When it can open, the whole card is the open control: a
 * `role="button"` div rather than a `<button>`, because the version picker and
 * the trailing actions are real buttons and HTML forbids nesting those (see
 * NestedButton for the same call). With no open action it is a plain container,
 * so an active button inside it (like "See all") is not announced as disabled.
 * Inner controls stop propagation so they don't open it.
 *
 * Shared by the artifacts panel and the cards the thread draws inline, so a
 * file reads the same wherever it is shown.
 */
export function ArtifactCard({
  icon,
  title,
  meta,
  onOpen,
  onHoverStart,
  actions,
  className,
}: {
  icon: ReactNode;
  title: string;
  meta?: ReactNode;
  onOpen?: () => void;
  onHoverStart?: () => void;
  /** Always-visible trailing cluster: comment badge, download, open externally. */
  actions?: ReactNode;
  className?: string;
}) {
  const body = (
    <>
      <div className="relative flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md bg-gray-4">
        {/* The icon again, blown up and blurred: the tile tints itself with
            the icon's own colors, so new icons never need a color mapping. */}
        <div
          aria-hidden
          className="absolute inset-0 flex scale-[2.4] items-center justify-center opacity-40 blur-[9px] saturate-[1.8] dark:opacity-70"
        >
          {icon}
        </div>
        <div className="relative flex items-center justify-center">{icon}</div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{title}</div>
        {meta && (
          <div className="flex items-center gap-1 whitespace-nowrap text-[12px] text-muted-foreground">
            {meta}
          </div>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-1">{actions}</div>
      )}
    </>
  );

  const baseClass =
    "flex w-full items-center gap-2.5 rounded-lg border border-border bg-muted py-2 pr-1.5 pl-2 text-[13px] transition-colors";

  // With no open action the card is inert, so it stays a plain container: no
  // button role or disabled state for the actions inside it to inherit.
  if (!onOpen) {
    return (
      <div data-artifact-card className={cn(baseClass, className)}>
        {body}
      </div>
    );
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: nested real buttons forbid a <button> card
    <div
      data-artifact-card
      role="button"
      tabIndex={0}
      aria-label={`View ${title}`}
      className={cn(
        baseClass,
        "cursor-pointer hover:border-gray-6 hover:bg-gray-3",
        className,
      )}
      onClick={onOpen}
      onKeyDown={(event) => {
        // Only the card itself: inner controls' key presses bubble up here.
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      onPointerEnter={onHoverStart}
      onFocus={onHoverStart}
    >
      {body}
    </div>
  );
}

/** Inner controls of a card: their clicks must not open the card behind them. */
export function stopCardOpen(event: { stopPropagation: () => void }): void {
  event.stopPropagation();
}
