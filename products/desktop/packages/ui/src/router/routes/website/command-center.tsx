import { CommandCenterView } from "@posthog/ui/features/command-center/components/CommandCenterView";
import { createFileRoute } from "@tanstack/react-router";

// Channels-space mirror of /command-center. Renders the same shared
// CommandCenterView so the page stays single-source; only the route entry is
// duplicated so navigating here keeps the channels chrome (rail + channel
// sidebar).
export const Route = createFileRoute("/website/command-center")({
  component: CommandCenterView,
});
