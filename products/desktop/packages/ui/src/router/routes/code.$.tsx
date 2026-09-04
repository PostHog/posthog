import { redirectFromLegacyPath } from "@posthog/ui/router/legacyPaths";
import { createFileRoute } from "@tanstack/react-router";

// Tasks, the inbox, agents and loops lost their `/code` prefix when the routes
// were flattened. Old links still arrive from deep links, notifications and
// restored history, so they get sent on to where the page lives now.
export const Route = createFileRoute("/code/$")({
  beforeLoad: ({ location }) => redirectFromLegacyPath(location),
});
