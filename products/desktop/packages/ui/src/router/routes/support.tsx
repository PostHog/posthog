import { SupportView } from "@posthog/ui/features/support/components/SupportView";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/support")({
  component: SupportView,
  ...withRouteSkeleton(AppPageSkeleton),
});
