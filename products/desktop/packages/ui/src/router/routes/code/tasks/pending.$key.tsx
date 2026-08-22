import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/tasks/pending/$key")(
  legacyRedirect({ to: "/tasks/pending/$key" }),
);
