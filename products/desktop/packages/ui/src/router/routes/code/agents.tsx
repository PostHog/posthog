import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents")({
  component: AgentsLayout,
  ...withRouteSkeleton(AppPageSkeleton),
});

function AgentsLayout() {
  return <Outlet />;
}
