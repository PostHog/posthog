import { TodayView } from "@posthog/ui/features/today/TodayView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/today")({
  component: TodayView,
});
