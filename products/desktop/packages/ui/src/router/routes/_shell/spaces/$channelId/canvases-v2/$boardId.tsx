import { BoardView } from "@posthog/ui/features/canvas-v2/components/BoardView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_shell/spaces/$channelId/canvases-v2/$boardId",
)({
  component: SpaceBoardRoute,
});

function SpaceBoardRoute() {
  const { channelId, boardId } = Route.useParams();
  return <BoardView boardId={boardId} channelId={channelId} />;
}
