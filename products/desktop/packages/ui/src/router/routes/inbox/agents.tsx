import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/agents")({
  component: InboxAgentsRedirect,
});

function InboxAgentsRedirect() {
  return <Navigate to="/agents" replace />;
}
