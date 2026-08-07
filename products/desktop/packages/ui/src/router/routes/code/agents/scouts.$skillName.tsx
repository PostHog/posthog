import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/scouts/$skillName")({
  component: Outlet,
});
