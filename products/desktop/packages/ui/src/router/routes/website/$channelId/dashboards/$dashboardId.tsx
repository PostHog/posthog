import { WebsiteDashboard } from "@posthog/ui/features/canvas/components/WebsiteDashboard";
import {
  CanvasSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/website/$channelId/dashboards/$dashboardId",
)({
  component: DashboardRoute,
  ...withRouteSkeleton(CanvasSkeleton),
});

function DashboardRoute() {
  const { dashboardId } = Route.useParams();
  return <WebsiteDashboard dashboardId={dashboardId} />;
}
