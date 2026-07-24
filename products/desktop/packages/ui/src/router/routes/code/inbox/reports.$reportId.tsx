import type { SignalReport } from "@posthog/shared/types";
import { ReportDetail } from "@posthog/ui/features/inbox/components/ReportDetail";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/reports/$reportId")({
  component: ReportDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function ReportDetailRoute() {
  const { reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  return <ReportDetail reportId={reportId} cachedReport={cachedReport} />;
}
