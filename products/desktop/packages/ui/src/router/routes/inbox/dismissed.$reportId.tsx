import { reportNavigationState } from "@posthog/ui/router/reportNavigation";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/dismissed/$reportId")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/reports/$reportId",
      params: { reportId: params.reportId },
      search: { from: "/inbox/dismissed" },
      state: reportNavigationState,
      replace: true,
    });
  },
});
