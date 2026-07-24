import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/$loopId")({
  component: Outlet,
});
