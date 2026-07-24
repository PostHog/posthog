import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/")({
  component: InboxIndexRedirect,
});

function InboxIndexRedirect() {
  return <Navigate to="/code/inbox/pulls" replace />;
}
