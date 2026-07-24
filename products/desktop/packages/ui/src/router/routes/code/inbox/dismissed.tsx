import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/dismissed")({
  component: Outlet,
});
