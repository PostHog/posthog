import type { SignalReport } from "@posthog/shared/types";
import { DismissedReportDetail } from "@posthog/ui/features/inbox/components/DismissedReportDetail";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/dismissed/$reportId")({
  component: DismissedReportDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function DismissedReportDetailRoute() {
  const { reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  return (
    <DismissedReportDetail reportId={reportId} cachedReport={cachedReport} />
  );
}
