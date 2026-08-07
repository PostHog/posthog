import type { SignalReport } from "@posthog/shared/types";
import { PullRequestDetail } from "@posthog/ui/features/inbox/components/PullRequestDetail";
import { getCachedInboxReportDetail } from "@posthog/ui/features/inbox/inboxQueries";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/pulls/$reportId")({
  component: PullRequestDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SignalReport | null =>
    getCachedInboxReportDetail(params.reportId) ?? null,
});

function PullRequestDetailRoute() {
  const { reportId } = Route.useParams();
  const cachedReport = Route.useLoaderData();
  return <PullRequestDetail reportId={reportId} cachedReport={cachedReport} />;
}
