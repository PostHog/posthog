import { Spinner } from "@posthog/quill";
import { useReportSpace } from "@posthog/ui/features/canvas/hooks/useReportSpace";
import { createFileRoute, Navigate, useParams } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox")({
  component: LegacyInboxRedirect,
});

function LegacyInboxRedirect() {
  const { reportSpaceId } = useReportSpace();
  const { reportId } = useParams({ strict: false });
  if (!reportSpaceId) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (reportId) {
    return (
      <Navigate
        replace
        to="/website/$channelId/reports/$reportId"
        params={{ channelId: reportSpaceId, reportId }}
      />
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
