import { SupportListView } from "@posthog/ui/features/support/components/SupportListView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/support/")({
  component: SupportListView,
});
