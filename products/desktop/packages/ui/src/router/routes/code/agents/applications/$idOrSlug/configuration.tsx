import { AgentConfigurationPane } from "@posthog/ui/features/agent-applications/components/AgentConfigurationPane";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/configuration",
)({
  validateSearch: (
    search: Record<string, unknown>,
  ): { node?: string; revision?: string } => ({
    node: typeof search.node === "string" ? search.node : undefined,
    revision: typeof search.revision === "string" ? search.revision : undefined,
  }),
  component: AgentConfigurationRoute,
});

function AgentConfigurationRoute() {
  const { idOrSlug } = Route.useParams();
  const { node, revision } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <AgentConfigurationPane
      idOrSlug={idOrSlug}
      selectedNode={node ?? null}
      onSelectNode={(next) =>
        navigate({ search: (prev) => ({ ...prev, node: next }) })
      }
      selectedRevisionId={revision ?? null}
      onSelectRevision={(revisionId) =>
        navigate({ search: (prev) => ({ ...prev, revision: revisionId }) })
      }
      onOpenSession={(sessionId) =>
        navigate({
          to: "/code/agents/applications/$idOrSlug/sessions/$sessionId",
          params: { idOrSlug, sessionId },
        })
      }
    />
  );
}
