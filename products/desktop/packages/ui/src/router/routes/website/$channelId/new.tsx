import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

// The space becomes `?channel=` on the canonical new-task screen.
export const Route = createFileRoute("/website/$channelId/new")(
  legacyRedirect({
    to: "/new",
    search: (prev, params) => ({ ...prev, channel: params.channelId }),
  }),
);
