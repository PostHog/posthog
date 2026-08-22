import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/feeds/$feedId")(
  legacyRedirect({ to: "/feeds/$feedId" }),
);
