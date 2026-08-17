import { Spinner } from "@posthog/quill";
import { useReportSpace } from "@posthog/ui/features/canvas/hooks/useReportSpace";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { createFileRoute, Navigate, useParams } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/code/inbox")({
  component: LegacyInboxRedirect,
});

function LegacyInboxRedirect() {
  const { reportSpaceId } = useReportSpace();
  const { reportId } = useParams({ strict: false });
  const openReport = useOpenInboxReport();
  useEffect(() => {
    if (reportId) void openReport(reportId);
  }, [openReport, reportId]);
  if (!reportSpaceId) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (reportId) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <Navigate
      replace
      to="/website/$channelId"
      params={{ channelId: reportSpaceId }}
    />
  );
}
