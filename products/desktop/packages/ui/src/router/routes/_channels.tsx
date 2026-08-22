import { WebsiteLayout } from "@posthog/ui/features/canvas/components/WebsiteLayout";
import { createFileRoute } from "@tanstack/react-router";

// Pathless chrome: the channels destinations live at clean root URLs
// (/home, /activity, /feeds/:id, /new, /tasks/:id) but render with the same
// in-pane header machinery as /spaces/*. The layout itself decides per path
// when the legacy chrome owns the header instead.
export const Route = createFileRoute("/_channels")({
  component: WebsiteLayout,
});
