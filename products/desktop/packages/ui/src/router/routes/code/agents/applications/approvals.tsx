import { AgentFleetApprovalsPane } from "@posthog/ui/features/agent-applications/components/AgentFleetApprovalsPane";
import type { ApprovalFilter } from "@posthog/ui/features/agent-applications/components/agentApprovalsFilters";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

export const Route = createFileRoute("/code/agents/applications/approvals")({
  validateSearch: (search: Record<string, unknown>): { request?: string } => ({
    request: typeof search.request === "string" ? search.request : undefined,
  }),
  component: AgentFleetApprovalsRoute,
});

function AgentFleetApprovalsRoute() {
  const { request } = Route.useSearch();
  const navigate = Route.useNavigate();
  const [filter, setFilter] = useState<ApprovalFilter>("queued");

  return (
    <AgentFleetApprovalsPane
      selectedId={request ?? null}
      onSelect={(id) =>
        navigate({
          search: (prev) => ({ ...prev, request: id ?? undefined }),
        })
      }
      filter={filter}
      onFilterChange={setFilter}
    />
  );
}
