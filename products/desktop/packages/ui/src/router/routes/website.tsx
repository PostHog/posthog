import { WebsiteLayout } from "@posthog/ui/features/canvas/components/WebsiteLayout";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website")({
  component: WebsiteLayout,
});
