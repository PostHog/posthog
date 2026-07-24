import { PullRequestsTab } from "@posthog/ui/features/inbox/components/PullRequestsTab";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/pulls/")({
  component: PullRequestsTab,
});
