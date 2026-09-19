import { WebsiteDashboardsIndex } from "@posthog/ui/features/canvas/components/WebsiteDashboardsIndex";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/canvases")({
  component: ChannelCanvasesRoute,
});

function ChannelCanvasesRoute() {
  const { channelId } = Route.useParams();
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="canvases">
        <WebsiteDashboardsIndex channelId={channelId} variant="work" />
      </SpaceTabbedPage>
    );
  }
  return <WebsiteDashboardsIndex channelId={channelId} />;
}
