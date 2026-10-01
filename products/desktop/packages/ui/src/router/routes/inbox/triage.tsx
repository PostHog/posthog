import { createFileRoute } from "@tanstack/react-router";

// `InboxView` renders triage for this path, the way it renders the list for
// `/inbox/reports`, so the route itself only has to exist.
export const Route = createFileRoute("/inbox/triage")({
  component: () => null,
});
