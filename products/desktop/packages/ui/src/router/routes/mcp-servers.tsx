import { legacyRedirect } from "@posthog/ui/router/legacyRedirect";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/mcp-servers")(
  legacyRedirect({
    to: "/settings/$category",
    params: { category: "mcp-servers" },
  }),
);
