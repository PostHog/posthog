import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";

/**
 * Whether a publish landed after the public link was pinned, so there is a newer
 * version "Publish changes" can move the link to. False while the canvas is not
 * shared publicly.
 */
export function publicLinkHasUnpublishedChanges(
  dashboard:
    | Pick<DashboardRecord, "publishedBuildId" | "sharedBuildId">
    | null
    | undefined,
): boolean {
  if (!dashboard?.sharedBuildId || !dashboard.publishedBuildId) return false;
  return dashboard.sharedBuildId !== dashboard.publishedBuildId;
}
