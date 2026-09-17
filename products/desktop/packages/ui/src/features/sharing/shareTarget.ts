import type { ChannelsSurface } from "@posthog/shared/analytics-events";

/** What a share dialog is about: a canvas in a space, or a file a task run produced. */
export type ShareTarget =
  | { kind: "canvas"; channelId: string; dashboardId: string; name: string }
  | {
      kind: "artifact";
      taskId: string;
      runId: string;
      artifactId: string;
      name: string;
    };

export type ShareSurface = ChannelsSurface;

/** Who can open the thing today, from the visibility of the space it lives in. */
export type ShareVisibility = "project" | "personal" | "unknown";
