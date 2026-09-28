import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/activity")({
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/spaces/$channelId", params });
  },
});
