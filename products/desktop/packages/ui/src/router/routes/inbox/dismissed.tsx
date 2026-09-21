import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/dismissed")({
  component: Outlet,
});
