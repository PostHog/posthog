import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

/**
 * The shared page header section. Full-bleed (the page body below it keeps its
 * own container), bordered off from the content, and composed from parts so
 * each surface takes only what it needs:
 *
 *   <PageHeader>
 *     <PageHeaderHeading>
 *       <PageHeaderTitleRow>
 *         <PageHeaderTitle>Inbox</PageHeaderTitle>
 *         <PageHeaderChip icon={…}>Runs in the cloud</PageHeaderChip>
 *         <PageHeaderActions>…</PageHeaderActions>
 *       </PageHeaderTitleRow>
 *       <PageHeaderDescription>…</PageHeaderDescription>
 *     </PageHeaderHeading>
 *     <PageHeaderNav>
 *       <SomeTabBar />
 *       <PageHeaderFilters>…</PageHeaderFilters>
 *     </PageHeaderNav>
 *   </PageHeader>
 *
 * Layout base is the Inbox header (full width, title + description + tab bar);
 * the chip comes from Loops.
 */
export function PageHeader({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex shrink-0 cursor-default flex-col gap-3 border-(--gray-5) border-b px-6 pt-5 pb-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Title row + description, tight against each other. */
export function PageHeaderHeading({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      {children}
    </div>
  );
}

/** The title line: title, any chips, and (pushed right) actions. */
export function PageHeaderTitleRow({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center gap-2", className)}>
      {children}
    </div>
  );
}

export function PageHeaderTitle({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <h1
      className={cn(
        "min-w-0 truncate font-bold text-[22px] text-gray-12 leading-tight tracking-tight",
        className,
      )}
    >
      {children}
    </h1>
  );
}

/** A pill next to the title — a count, a mode, "Runs entirely in the cloud". */
export function PageHeaderChip({
  icon,
  className,
  children,
}: {
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-full bg-(--accent-a3) px-2.5 py-1 font-medium text-(--accent-11) text-[11px] leading-none",
        className,
      )}
    >
      {icon}
      <span className="whitespace-nowrap">{children}</span>
    </span>
  );
}

export function PageHeaderDescription({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <p
      className={cn(
        "max-w-3xl text-[12.5px] text-muted-foreground leading-snug",
        className,
      )}
    >
      {children}
    </p>
  );
}

/** Trailing controls on the title line (create buttons, view switchers). */
export function PageHeaderActions({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  // -my-1 keeps a 32px control from stretching the title row past the
  // title's own line box, which would shift the title and description down.
  return (
    <div
      className={cn(
        "-my-1 ml-auto flex shrink-0 items-center gap-2",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * The sub-nav row: a tab strip, with filters pushed to the right. Cancels the
 * header's bottom padding so an underlined tab strip sits on the header border
 * the way the Inbox tabs do; the tabs' own padding keeps the breathing room.
 */
export function PageHeaderNav({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "-mb-4 flex min-w-0 items-center justify-between",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Filters/controls sitting to the right of the sub-nav. */
export function PageHeaderFilters({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("ml-auto flex shrink-0 items-center gap-2", className)}>
      {children}
    </div>
  );
}
