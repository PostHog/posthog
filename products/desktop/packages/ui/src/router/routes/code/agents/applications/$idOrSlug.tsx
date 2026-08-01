import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/applications/$idOrSlug")({
  component: Outlet,
});
