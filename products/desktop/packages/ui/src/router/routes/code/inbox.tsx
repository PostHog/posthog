import { REPORT_CANVAS_INBOX_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { InboxView } from "@posthog/ui/features/inbox/components/InboxView";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import {
  createFileRoute,
  useLocation,
  useParams,
} from "@tanstack/react-router";
import { type ReactElement, useEffect, useRef } from "react";

export const Route = createFileRoute("/code/inbox")({
  component: InboxRoute,
  ...withRouteSkeleton(AppPageSkeleton),
});

function InboxRoute(): ReactElement {
  const reportCanvasesEnabled = useFeatureFlag(
    REPORT_CANVAS_INBOX_FLAG,
    import.meta.env.DEV,
  );
  const { reportId } = useParams({ strict: false });
  const { pathname } = useLocation();
  const openReport = useOpenInboxReport();
  const openedReportId = useRef<string | null>(null);
  const isSignalReportDetail = ["reports", "pulls", "dismissed"].some((tab) =>
    pathname.startsWith(`/code/inbox/${tab}/`),
  );

  useEffect(() => {
    if (
      reportCanvasesEnabled &&
      isSignalReportDetail &&
      reportId &&
      openedReportId.current !== reportId
    ) {
      openedReportId.current = reportId;
      void openReport(reportId);
    }
  }, [isSignalReportDetail, openReport, reportCanvasesEnabled, reportId]);

  return <InboxView />;
}
