import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/agents")({
  beforeLoad: () => {
    throw redirect({ to: "/agents", replace: true });
  },
});
