import { WebsiteChannelsIndex } from "@posthog/ui/features/canvas/components/WebsiteChannelsIndex";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/spaces/")({
  component: WebsiteChannelsIndex,
});
