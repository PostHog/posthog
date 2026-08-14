import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/website/skills")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "skills" },
      replace: true,
    });
  },
});
