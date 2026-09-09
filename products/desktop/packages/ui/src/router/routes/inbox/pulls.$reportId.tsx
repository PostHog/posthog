import { legacyReportNavigationState } from "@posthog/ui/router/reportNavigation";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/pulls/$reportId")({
  beforeLoad: ({ params, location }) => {
    throw redirect({
      to: "/reports/$reportId",
      params: { reportId: params.reportId },
      state: legacyReportNavigationState(location.state),
      replace: true,
    });
  },
});
