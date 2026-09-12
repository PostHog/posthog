import { SpaceFilesRoute } from "@posthog/ui/features/space-files/SpaceFilesRoute";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/files")({
  validateSearch: (search: Record<string, unknown>) => ({
    file:
      typeof search.file === "string" && search.file ? search.file : undefined,
  }),
  component: SpaceFilesRoute,
});
