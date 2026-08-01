import { AgentChatPane } from "@posthog/ui/features/agent-applications/components/AgentChatPane";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/chat",
)({
  // `revision` routes this chat to a non-live revision (the pane mints a
  // short-lived ingress JWT scoped to that revision; side effects still run
  // for real, only the revision serving the request changes). `session`
  // re-attaches a specific session on mount — set by rail clicks that cross
  // revisions so the new mount resumes the right conversation instead of
  // starting empty.
  validateSearch: (
    search: Record<string, unknown>,
  ): { revision?: string; session?: string } => ({
    revision: typeof search.revision === "string" ? search.revision : undefined,
    session: typeof search.session === "string" ? search.session : undefined,
  }),
  component: AgentChatRoute,
});

function AgentChatRoute() {
  const { idOrSlug } = Route.useParams();
  const { revision, session } = Route.useSearch();
  return (
    <AgentChatPane
      idOrSlug={idOrSlug}
      revisionId={revision ?? null}
      resumeSessionId={session ?? null}
    />
  );
}
