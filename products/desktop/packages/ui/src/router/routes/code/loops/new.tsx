import { LoopForm } from "@posthog/ui/features/loops/components/LoopForm";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/new")({
  component: LoopForm,
});
