import { LibraryView } from "@posthog/ui/features/library/LibraryView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/library/$")({
  component: LibraryView,
});
