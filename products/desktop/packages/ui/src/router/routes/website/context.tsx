import { ContextWikiView } from "@posthog/ui/features/context-wiki/components/ContextWikiView";
import { createFileRoute } from "@tanstack/react-router";

// Channels-space mirror of /context. Renders the same shared ContextWikiView
// so the page stays single-source; only the route entry is duplicated so
// navigating here keeps the channels chrome (rail + channel sidebar).
export const Route = createFileRoute("/website/context")({
  component: ContextWikiView,
});
