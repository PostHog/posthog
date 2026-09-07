import { WebsiteDashboardsIndex } from "@posthog/ui/features/canvas/components/WebsiteDashboardsIndex";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/canvases")({
  component: ChannelCanvasesRoute,
});

function ChannelCanvasesRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteDashboardsIndex channelId={channelId} />;
}
