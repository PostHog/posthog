import { asInboxBackTarget } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { reportNavigationState } from "@posthog/ui/router/reportNavigation";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/dismissed/$reportId")({
  beforeLoad: ({ params, location }) => {
    // The run-detail gate records where the open run came from when it
    // redirects an archived report here. Follow that path in (e.g. back to
    // Runs, not Archive) and fall back to the Archive tab when there is none.
    const from =
      asInboxBackTarget(location.state.inboxBackOrigin)?.to ??
      "/inbox/dismissed";
    throw redirect({
      to: "/reports/$reportId",
      params: { reportId: params.reportId },
      search: { from },
      state: reportNavigationState,
      replace: true,
    });
  },
});
