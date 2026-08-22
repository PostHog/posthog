import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/artifacts")(
  legacyRedirect({ to: "/spaces/$channelId/artifacts" }),
);
