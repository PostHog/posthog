import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/scouts")({
  component: Outlet,
});
