import { BoardView } from "@posthog/ui/features/canvas-v2/components/BoardView";
import { CanvasV2Gate } from "@posthog/ui/features/canvas-v2/components/CanvasV2Gate";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_shell/spaces/$channelId/canvases-v2/$boardId",
)({
  component: SpaceBoardRoute,
});

function SpaceBoardRoute() {
  const { channelId, boardId } = Route.useParams();
  return (
    <CanvasV2Gate>
      <BoardView boardId={boardId} channelId={channelId} />
    </CanvasV2Gate>
  );
}
