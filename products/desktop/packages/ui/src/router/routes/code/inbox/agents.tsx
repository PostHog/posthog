import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/agents")({
  component: InboxAgentsRedirect,
});

function InboxAgentsRedirect() {
  return <Navigate to="/code/agents" replace />;
}
