import { InboxView } from "@posthog/ui/features/inbox/components/InboxView";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox")({
  component: InboxView,
  ...withRouteSkeleton(AppPageSkeleton),
});
