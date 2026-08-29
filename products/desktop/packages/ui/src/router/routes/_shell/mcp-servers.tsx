import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/mcp-servers")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "mcp-servers" },
      replace: true,
    });
  },
});
