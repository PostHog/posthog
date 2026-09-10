import type { AgentsPageSearch } from "@posthog/ui/features/agents/agentsPageStore";
import { createFileRoute, redirect } from "@tanstack/react-router";

// The agents pages became the Agents settings page, which has one URL for all
// of its tabs. Old hrefs still arrive from deep links, notifications and
// restored history. Findings links open Self-driving; other links open the
// tab or the agent they named. The redirect carries the target in its search —
// a bare redirect would land on the fleet and drop what the href named.
export const Route = createFileRoute("/agents/$")({
  beforeLoad: ({ params, location }) => {
    const rest = (params._splat ?? "").replace(/^scouts\/?/, "");
    const search = location.search as { finding?: unknown };
    const finding =
      typeof search.finding === "string" ? search.finding : undefined;

    if (rest === "findings") {
      throw redirect({ to: "/inbox", replace: true });
    } else if (rest === "scratchpad") {
      throw agentRedirect({ tab: "memory" });
    } else if (rest) {
      throw agentRedirect({ agent: rest.split("/")[0], finding });
    } else {
      throw agentRedirect({ tab: "agents" });
    }
  },
});

function agentRedirect(
  target: Pick<AgentsPageSearch, "tab"> &
    Partial<Pick<AgentsPageSearch, "agent" | "finding">>,
): never {
  const search: AgentsPageSearch = {
    ...(target.tab ? { tab: target.tab } : {}),
    ...(target.agent ? { agent: target.agent } : {}),
    ...(target.finding ? { finding: target.finding } : {}),
  };
  throw redirect({
    to: "/settings/$category",
    params: { category: "agents" },
    search,
    replace: true,
  });
}
