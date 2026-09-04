import { BoardView } from "@posthog/ui/features/canvas-v2/components/BoardView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/canvases-v2/$boardId")({
  component: BoardRoute,
});

function BoardRoute() {
  const { boardId } = Route.useParams();
  return <BoardView boardId={boardId} />;
}
