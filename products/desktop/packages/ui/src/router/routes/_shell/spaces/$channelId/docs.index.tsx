import { createFileRoute, redirect } from "@tanstack/react-router";

// The space's pages live on its context page, so a bare /docs link goes there
// rather than to a second list of the same pages.
export const Route = createFileRoute("/_shell/spaces/$channelId/docs/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/spaces/$channelId/context",
      params: { channelId: params.channelId },
    });
  },
});
