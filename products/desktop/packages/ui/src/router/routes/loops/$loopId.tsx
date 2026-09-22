import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/loops/$loopId")({
  component: Outlet,
});
