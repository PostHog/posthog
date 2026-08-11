import { createFileRoute, redirect } from "@tanstack/react-router";

// Redirect so restored windows and stale history entries land on the merged
// Plan & usage settings page instead of a not-found screen.
export const Route = createFileRoute("/usage")({
  beforeLoad: () => {
    throw redirect({
      to: "/settings/$category",
      params: { category: "plan-usage" },
      replace: true,
    });
  },
});
