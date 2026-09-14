import type { SignalReport } from "@posthog/shared/types";
import { ReportPage } from "@posthog/ui/features/inbox/components/ReportPage";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { validSourceHref } from "@posthog/ui/router/reportNavigation";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/reports/$reportId")({
  component: ReportRoute,
  validateSearch: (search: Record<string, unknown>): { from?: string } => {
    const from = validSourceHref(search.from);
    return from ? { from } : {};
  },
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function ReportRoute() {
  const { reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  return <ReportPage reportId={reportId} cachedReport={cachedReport} />;
}
