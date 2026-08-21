import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/")({
  beforeLoad: () => {
    throw redirect({ to: "/code/agents/scouts" });
  },
});
