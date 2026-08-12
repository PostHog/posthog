import { ActivityView } from "@posthog/ui/features/canvas/components/ActivityView";
import { createFileRoute } from "@tanstack/react-router";

// Channels-space Activity page: every task the viewer is involved in — created,
// @-mentioned in, or messaged in — across channels. The sidebar's Activity nav
// badge counts what's new here.
export const Route = createFileRoute("/website/activity")({
  component: ActivityView,
});
