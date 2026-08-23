import { ContextWikiView } from "@posthog/ui/features/context-wiki/components/ContextWikiView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/context")({
  component: ContextWikiView,
});
