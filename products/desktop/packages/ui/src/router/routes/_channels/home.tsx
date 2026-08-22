import { WebsiteHome } from "@posthog/ui/features/canvas/grid/WebsiteHome";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_channels/home")({
  component: WebsiteHome,
});
