import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/loops/$loopId")({
  component: Outlet,
});
