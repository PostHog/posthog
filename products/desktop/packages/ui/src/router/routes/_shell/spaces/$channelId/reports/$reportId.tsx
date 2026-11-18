import { reportNavigationState } from "@posthog/ui/router/reportNavigation";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_shell/spaces/$channelId/reports/$reportId",
)({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/reports/$reportId",
      params: { reportId: params.reportId },
      search: { from: `/spaces/${params.channelId}` },
      state: reportNavigationState,
      replace: true,
    });
  },
});
