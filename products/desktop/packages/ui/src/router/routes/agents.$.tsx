import { agentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import { createFileRoute, redirect } from "@tanstack/react-router";

// The agents pages became the Agents settings page, which has one URL for all
// of its tabs. Old hrefs still arrive from deep links, notifications and
// restored history, so each one opens the tab or the agent it named.
export const Route = createFileRoute("/agents/$")({
  beforeLoad: ({ params, location }) => {
    const rest = (params._splat ?? "").replace(/^scouts\/?/, "");
    const actions = agentsPageActions();

    if (rest === "findings") {
      actions.showTab("signals");
    } else if (rest === "scratchpad") {
      actions.showTab("memory");
    } else if (rest) {
      const finding = (location.search as { finding?: unknown }).finding;
      actions.openAgent(rest.split("/")[0], {
        findingId: typeof finding === "string" ? finding : undefined,
      });
    } else {
      actions.showTab("agents");
    }

    throw redirect({
      to: "/settings/$category",
      params: { category: "agents" },
      replace: true,
    });
  },
});
