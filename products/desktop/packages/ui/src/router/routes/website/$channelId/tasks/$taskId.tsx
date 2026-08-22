import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

// The space becomes `?from=` on the canonical task screen.
export const Route = createFileRoute("/website/$channelId/tasks/$taskId")(
  legacyRedirect({
    to: "/tasks/$taskId",
    search: (prev, params) => ({ ...prev, from: params.channelId }),
  }),
);
