import { ActivityView } from "@posthog/ui/features/canvas/components/ActivityView";
import { createFileRoute } from "@tanstack/react-router";

// Channels-space Activity page: @-mentions of the viewer across channel
// threads. The sidebar's Activity nav badge counts what's new here.
export const Route = createFileRoute("/website/activity")({
  component: ActivityView,
});
