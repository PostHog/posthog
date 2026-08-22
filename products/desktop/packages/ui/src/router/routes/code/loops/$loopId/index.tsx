import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/$loopId/")(
  legacyRedirect({ to: "/loops/$loopId" }),
);
