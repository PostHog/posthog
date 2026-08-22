import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/reports/$reportId")(
  legacyRedirect({ to: "/inbox/reports/$reportId" }),
);
