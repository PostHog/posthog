import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/runs")({
  component: Outlet,
});
