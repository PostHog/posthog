import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/artifacts")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/website/$channelId",
      params: { channelId: params.channelId },
      replace: true,
    });
  },
});
