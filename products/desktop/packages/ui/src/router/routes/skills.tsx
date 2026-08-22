import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/skills")(
  legacyRedirect({ to: "/settings/$category", params: { category: "skills" } }),
);
