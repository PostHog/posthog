import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/classic")({
  beforeLoad: () => {
    throw redirect({ to: "/library", replace: true });
  },
});
