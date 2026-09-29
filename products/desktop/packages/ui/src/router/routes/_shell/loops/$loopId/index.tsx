import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { LoopDetailView } from "@posthog/ui/features/loops/components/LoopDetailView";
import { useLoop } from "@posthog/ui/features/loops/hooks/useLoop";
import { useLoopScope } from "@posthog/ui/features/loops/hooks/useLoopScope";
import { parseLoopDetailSearch } from "@posthog/ui/features/loops/loopDetailSearch";
import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/loops/$loopId/")({
  component: LoopDetailRoute,
  validateSearch: parseLoopDetailSearch,
});

function LoopDetailRoute() {
  const { loopId } = Route.useParams();
  const { edit } = Route.useSearch();
  const { data: loop, isLoading } = useLoop(loopId);
  const { isLoading: channelsLoading } = useChannels();
  const scope = useLoopScope(loop);
  if (isLoading || channelsLoading) return null;
  if (scope?.kind === "space" && scope.available) {
    return (
      <Navigate
        replace
        to="/spaces/$channelId/loops/$loopId"
        params={{ channelId: scope.channelId, loopId }}
        search={{ edit }}
      />
    );
  }
  return <LoopDetailView loopId={loopId} startEditing={edit === true} />;
}
