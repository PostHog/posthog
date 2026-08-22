import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/tasks/$taskId")(
  legacyRedirect({ to: "/tasks/$taskId" }),
);
