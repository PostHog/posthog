import { Spinner } from "@posthog/quill";
import { REPORT_CANVAS_INBOX_FLAG } from "@posthog/shared";
import { useReportSpace } from "@posthog/ui/features/canvas/hooks/useReportSpace";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { InboxView } from "@posthog/ui/features/inbox/components/InboxView";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Navigate, useParams } from "@tanstack/react-router";
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
  return reportCanvasesEnabled ? <ReportCanvasRedirect /> : <InboxView />;
}

function ReportCanvasRedirect(): ReactElement {
  const { reportSpaceId } = useReportSpace();
  const { reportId } = useParams({ strict: false });
  const openReport = useOpenInboxReport();
  const openedReportId = useRef<string | null>(null);
  useEffect(() => {
    if (reportId && reportSpaceId && openedReportId.current !== reportId) {
      openedReportId.current = reportId;
      void openReport(reportId);
    }
  }, [openReport, reportId, reportSpaceId]);
  if (!reportSpaceId) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (reportId) {
    return <InboxView />;
  }
  return (
    <Navigate
      replace
      to="/website/$channelId"
      params={{ channelId: reportSpaceId }}
    />
  );
}
