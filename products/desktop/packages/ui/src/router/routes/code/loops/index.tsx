import { LoopsListView } from "@posthog/ui/features/loops/components/LoopsListView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/")({
  component: LoopsListView,
});
