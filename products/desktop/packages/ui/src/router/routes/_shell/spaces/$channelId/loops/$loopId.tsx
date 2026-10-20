import { LoopDetailView } from "@posthog/ui/features/loops/components/LoopDetailView";
import { parseLoopDetailSearch } from "@posthog/ui/features/loops/loopDetailSearch";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/loops/$loopId")(
  {
    component: ChannelLoopDetailRoute,
    validateSearch: parseLoopDetailSearch,
  },
);

function ChannelLoopDetailRoute() {
  const { loopId } = Route.useParams();
  const { edit } = Route.useSearch();
  return <LoopDetailView loopId={loopId} startEditing={edit === true} />;
}
