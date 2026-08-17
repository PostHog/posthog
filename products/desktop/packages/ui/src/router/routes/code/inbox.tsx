import { Spinner } from "@posthog/quill";
import { useGeneralSpace } from "@posthog/ui/features/canvas/hooks/useGeneralSpace";
import { createFileRoute, Navigate, useParams } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox")({
  component: LegacyInboxRedirect,
});

function LegacyInboxRedirect() {
  const { generalSpaceId } = useGeneralSpace();
  const { reportId } = useParams({ strict: false });
  if (!generalSpaceId) {
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
        params={{ channelId: generalSpaceId, reportId }}
      />
    );
  }
  return (
    <Navigate
      replace
      to="/website/$channelId"
      params={{ channelId: generalSpaceId }}
    />
  );
}
