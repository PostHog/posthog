import { redirectFromLegacyPath } from "@posthog/ui/router/legacyPaths";
import { createFileRoute } from "@tanstack/react-router";

// `/website` itself, which is now the spaces index. See website.$.tsx.
export const Route = createFileRoute("/website/")({
  beforeLoad: ({ location }) => redirectFromLegacyPath(location),
});
