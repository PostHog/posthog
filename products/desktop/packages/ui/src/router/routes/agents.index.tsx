import { agentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/")({
  beforeLoad: () => {
    agentsPageActions().showTab("agents");
    throw redirect({
      to: "/settings/$category",
      params: { category: "agents" },
      replace: true,
    });
  },
});
