import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/")({
  component: InboxIndexRedirect,
});

function InboxIndexRedirect() {
  return <Navigate to="/inbox/pulls" replace />;
}
