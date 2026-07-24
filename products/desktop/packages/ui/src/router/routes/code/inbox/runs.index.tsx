import { RunsTab } from "@posthog/ui/features/inbox/components/RunsTab";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/runs/")({
  component: RunsTab,
});
