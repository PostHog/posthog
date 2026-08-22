import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/spaces/$channelId/artifacts")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/spaces/$channelId",
      params: { channelId: params.channelId },
      replace: true,
    });
  },
});
