import type { SignalReport } from "@posthog/shared/types";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { ReportDetail } from "@posthog/ui/features/inbox/components/ReportDetail";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { createFileRoute } from "@tanstack/react-router";

// The in-space report detail: same body as the inbox detail, hosted inside the
// channels world so the space sidebar keeps its context. One route serves every
// report status, so the inbox's status↔route redirect is off.
export const Route = createFileRoute("/website/$channelId/reports/$reportId")({
  component: ChannelReportDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function ChannelReportDetailRoute() {
  const { channelId, reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  return (
    // ReportDetail owns its scroll (its chat dock sits beside the scrolling
    // report); this wrapper only hands it WebsiteLayout's outlet height.
    <div className="h-full min-h-0">
      <ReportDetail
        reportId={reportId}
        cachedReport={cachedReport}
        backTo={`/website/${channelId}`}
        backLabel={channelName ? `Back to #${channelName}` : "Back to space"}
        statusRedirect={false}
      />
    </div>
  );
}
