import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/settings/")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "general" },
    });
  },
});
