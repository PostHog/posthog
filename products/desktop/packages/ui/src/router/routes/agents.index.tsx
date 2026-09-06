import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "agents" },
      replace: true,
    });
  },
});
