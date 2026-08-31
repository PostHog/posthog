import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/scouts")({
  component: Outlet,
});
