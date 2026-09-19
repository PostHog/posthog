import { Skeleton } from "@posthog/quill";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import type { ReactElement } from "react";
import { yieldToPaint } from "./yieldToPaint";

/**
 * Per-route-kind pending skeletons, rendered as `pendingComponent` while a
 * route's loader awaits `yieldToPaint()`. They paint in the frame after a tab
 * click — before the destination's heavy mount — so they must stay trivially
 * cheap: static shapes only, no data, no hooks, no measurement.
 *
 * Each route kind gets its own silhouette so the loading state already reads
 * as the destination (chat thread vs. canvas grid vs. list), not a generic
 * spinner swap.
 */

/**
 * Route options for a skeleton-first navigation: paint `skeleton` for the
 * single frame `yieldToPaint()` holds the route pending, then mount the real
 * view behind it. Spread into `createFileRoute` options:
 *
 *   createFileRoute("/skills")({ component: SkillsView,
 *     ...withRouteSkeleton(AppPageSkeleton) })
 *
 * Routes with a real (cache-reading) loader can't use this — they await
 * `yieldToPaint()` inside their own loader and set `pendingComponent`
 * directly. Never await anything slower than a frame in a loader; a
 * network-blocked loader makes the route un-navigable when the fetch hangs.
 */
export function withRouteSkeleton(skeleton: () => ReactElement) {
  return { pendingComponent: skeleton, loader: yieldToPaint };
}

/** Task detail: chat thread (alternating agent/user bubbles) + composer bar. */
export function TaskDetailSkeleton() {
  return (
    <div className="flex h-full w-full flex-col">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 overflow-hidden px-4 pt-6">
        <div className="flex justify-end">
          <Skeleton className="h-14 w-[55%]" />
        </div>
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3.5 w-[40%]" />
          <Skeleton className="h-3.5 w-[85%]" />
          <Skeleton className="h-3.5 w-[70%]" />
        </div>
        <div className="flex justify-end">
          <Skeleton className="h-10 w-[35%]" />
        </div>
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3.5 w-[60%]" />
          <Skeleton className="h-3.5 w-[90%]" />
          <Skeleton className="h-3.5 w-[45%]" />
        </div>
      </div>
      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        <Skeleton className="h-22 w-full" />
      </div>
    </div>
  );
}

/** Canvas/dashboard: toolbar row + card grid. */
export function CanvasSkeleton() {
  return (
    <div className="flex h-full w-full flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <Skeleton className="h-6 w-45" />
        <div className="flex-1" />
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-20" />
      </div>
      <div className="grid flex-1 grid-cols-3 content-start gap-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    </div>
  );
}

/** Shared list-page silhouette: header row + subtitle + uniform rows. */
function ListPageSkeleton({
  maxWidthClass,
  rowHeightClass,
  rowCount,
  trailingAction,
}: {
  maxWidthClass: string;
  rowHeightClass: string;
  rowCount: number;
  trailingAction?: boolean;
}) {
  return (
    <div
      className={`mx-auto flex h-full w-full ${maxWidthClass} flex-col gap-4 p-6`}
    >
      <div className="flex items-center gap-3">
        <Skeleton className="h-7 w-55" />
        {trailingAction && (
          <>
            <div className="flex-1" />
            <Skeleton className="h-7 w-24" />
          </>
        )}
      </div>
      <Skeleton className="h-3.5 w-[50%]" />
      <div className="mt-2 flex flex-col gap-2">
        {Array.from({ length: rowCount }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton row
          <Skeleton key={i} className={`${rowHeightClass} w-full`} />
        ))}
      </div>
    </div>
  );
}

/** Channel pages (home / inbox / artifacts / history / context): header + rows. */
export function ChannelSkeleton() {
  return (
    <ListPageSkeleton
      maxWidthClass="max-w-4xl"
      rowHeightClass="h-14"
      rowCount={5}
    />
  );
}

/** Top-level app pages (home, inbox, agents, skills, MCP servers, command center). */
export function AppPageSkeleton() {
  return (
    <ListPageSkeleton
      maxWidthClass="max-w-5xl"
      rowHeightClass="h-12"
      rowCount={6}
      trailingAction
    />
  );
}

/**
 * The Work layout's space pages: the tab strip, then the shape of the tab
 * being opened. Every one starts at the strip's own inset, so the skeleton
 * lands where the content will.
 *
 * `useWorkLayout` is the one hook these may call — a flag read, no data — and
 * it is what keeps a flag-off user from seeing a silhouette of a layout they
 * do not have.
 */
function SpaceTabsFrame({ children }: { children: ReactElement }) {
  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-end gap-4 border-border border-b px-6 pt-2 pb-2">
        <Skeleton className="h-4 w-14" />
        <Skeleton className="h-4 w-14" />
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-4 w-14" />
      </div>
      {children}
    </div>
  );
}

/** A space's Activity tab: composer, a rule, then one-line rows under a day. */
export function SpaceActivitySkeleton() {
  return (
    <SpaceTabsFrame>
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col gap-3 px-6 pt-5">
          <div className="flex w-full max-w-[900px] flex-col gap-2 border-border border-b pb-4">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-4 w-44" />
          </div>
          <Skeleton className="h-3 w-14" />
          {Array.from({ length: 6 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton row
            <Skeleton key={i} className="h-7 w-full max-w-[900px]" />
          ))}
        </div>
        <div className="flex w-[276px] shrink-0 flex-col gap-2 border-border border-l px-3 pt-3">
          <Skeleton className="h-5 w-32" />
          {Array.from({ length: 4 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton row
            <Skeleton key={i} className="h-7 w-full" />
          ))}
        </div>
      </div>
    </SpaceTabsFrame>
  );
}

/** A space's Context tab: the chrome line, then goals and knowledge. */
export function SpaceContextSkeleton() {
  return (
    <SpaceTabsFrame>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-border border-b px-6">
          <Skeleton className="h-3.5 w-40" />
          <div className="flex-1" />
          <Skeleton className="h-7 w-28" />
          <Skeleton className="h-7 w-36" />
        </div>
        <div className="flex flex-col gap-6 px-6 pt-6">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-20 w-full max-w-md" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-12 w-full" />
        </div>
      </div>
    </SpaceTabsFrame>
  );
}

/** A space's Canvases tab: the count line, then the card grid. */
export function SpaceCanvasesSkeleton() {
  return (
    <SpaceTabsFrame>
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-6 py-5">
        <div className="flex items-center">
          <Skeleton className="h-3.5 w-20" />
          <div className="flex-1" />
          <Skeleton className="h-7 w-28" />
        </div>
        <div className="grid grid-cols-3 content-start gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton card
            <Skeleton key={i} className="h-56 w-full" />
          ))}
        </div>
      </div>
    </SpaceTabsFrame>
  );
}

/** A space's Settings tab: the description line, then its sections. */
export function SpaceSettingsSkeleton() {
  return (
    <SpaceTabsFrame>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center border-border border-b px-6">
          <Skeleton className="h-3.5 w-80" />
        </div>
        <div className="flex max-w-[800px] flex-col gap-7 px-6 pt-6">
          {Array.from({ length: 2 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton section
            <div key={i} className="flex flex-col gap-2">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-3 w-72" />
              <Skeleton className="h-16 w-full" />
            </div>
          ))}
        </div>
      </div>
    </SpaceTabsFrame>
  );
}

/**
 * The skeleton a space route paints: the tabbed one where that layout is on,
 * and the list silhouette the page had before it where it is not.
 */
export function spaceRouteSkeleton(
  tabbed: () => ReactElement,
): () => ReactElement {
  return function SpaceRouteSkeleton() {
    return useWorkLayout() ? tabbed() : <ChannelSkeleton />;
  };
}
