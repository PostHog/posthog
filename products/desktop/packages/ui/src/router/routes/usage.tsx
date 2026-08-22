import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/usage")(
  legacyRedirect({
    to: "/settings/$category",
    params: { category: "plan-usage" },
  }),
);
