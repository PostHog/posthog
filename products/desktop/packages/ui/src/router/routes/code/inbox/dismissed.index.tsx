import { DismissedTab } from "@posthog/ui/features/inbox/components/DismissedTab";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/dismissed/")({
  component: DismissedTab,
});
