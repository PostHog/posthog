import { ReportCanvas } from "@posthog/ui/features/canvas/reports/ReportCanvas";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/reports/$reportId")({
  component: ReportCanvasRoute,
});

function ReportCanvasRoute() {
  const { channelId, reportId } = Route.useParams();
  return <ReportCanvas channelId={channelId} reportId={reportId} />;
}
