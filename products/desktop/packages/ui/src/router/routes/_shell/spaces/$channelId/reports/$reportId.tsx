import type { SignalReport } from "@posthog/shared/types";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { ReportDetail } from "@posthog/ui/features/inbox/components/ReportDetail";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_shell/spaces/$channelId/reports/$reportId",
)({
  component: ChannelReportDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function ChannelReportDetailRoute() {
  const { channelId, reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  const { channels } = useChannels();
  const channelName = channels.find(
    (channel) => channel.id === channelId,
  )?.name;

  return (
    <div className="h-full min-h-0">
      <ReportDetail
        reportId={reportId}
        cachedReport={cachedReport}
        backTo={`/spaces/${channelId}`}
        backLabel={channelName ? `Back to #${channelName}` : "Back to space"}
        statusRedirect={false}
      />
    </div>
  );
}
