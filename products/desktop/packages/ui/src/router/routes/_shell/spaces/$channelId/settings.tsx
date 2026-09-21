import { SpaceSettings } from "@posthog/ui/features/canvas/components/SpaceSettings";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  SpaceSettingsSkeleton,
  spaceRouteSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/settings")({
  component: SettingsRoute,
  ...withRouteSkeleton(spaceRouteSkeleton(SpaceSettingsSkeleton)),
});

function SettingsRoute() {
  const { channelId } = Route.useParams();
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="settings">
        <SpaceSettings channelId={channelId} />
      </SpaceTabbedPage>
    );
  }
  return <SpaceSettings channelId={channelId} />;
}
