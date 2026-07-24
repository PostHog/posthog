import {
  AgentApprovalsPane,
  type ApprovalFilter,
} from "@posthog/ui/features/agent-applications/components/AgentApprovalsPane";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/approvals",
)({
  validateSearch: (search: Record<string, unknown>): { request?: string } => ({
    request: typeof search.request === "string" ? search.request : undefined,
  }),
  component: AgentApprovalsRoute,
});

function AgentApprovalsRoute() {
  const { idOrSlug } = Route.useParams();
  const { request } = Route.useSearch();
  const navigate = Route.useNavigate();
  const [filter, setFilter] = useState<ApprovalFilter>("queued");

  return (
    <AgentApprovalsPane
      idOrSlug={idOrSlug}
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
