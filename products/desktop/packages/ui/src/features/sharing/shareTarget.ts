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

/** Who can open the thing today, from the visibility of the space it lives in.
 *  A private space is membership-gated, so it is neither the whole project nor one person. */
export type ShareVisibility = "project" | "personal" | "private" | "unknown";

/** The audience a space's visibility implies. `undefined` while the space is still loading,
 *  which is "unknown" rather than a guess at the widest answer. */
export function shareVisibilityForChannel(
  channelType: "public" | "personal" | "private" | undefined,
  isLoading: boolean,
): ShareVisibility {
  if (channelType === "personal") return "personal";
  if (channelType === "private") return "private";
  if (channelType === "public") return "project";
  return isLoading ? "unknown" : "project";
}
