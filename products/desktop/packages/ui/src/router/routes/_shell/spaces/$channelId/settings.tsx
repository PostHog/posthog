import { SpaceSettings } from "@posthog/ui/features/canvas/components/SpaceSettings";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/settings")({
  component: SettingsRoute,
});

function SettingsRoute() {
  const { channelId } = Route.useParams();
  return <SpaceSettings channelId={channelId} />;
}
