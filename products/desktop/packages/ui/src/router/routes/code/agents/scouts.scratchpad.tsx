import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/scouts/scratchpad")(
  legacyRedirect({ to: "/agents/scouts/scratchpad" }),
);
