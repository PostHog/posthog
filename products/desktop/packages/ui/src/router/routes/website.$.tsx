import { redirectFromLegacyPath } from "@posthog/ui/router/legacyPaths";
import { createFileRoute } from "@tanstack/react-router";

// The spaces and the pages beside them lost their `/website` prefix when the
// routes were flattened. Old links still arrive from deep links, notifications
// and restored history, so they get sent on to where the page lives now.
export const Route = createFileRoute("/website/$")({
  beforeLoad: ({ location }) => redirectFromLegacyPath(location),
});
