import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/settings/")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "general" },
    });
  },
});
