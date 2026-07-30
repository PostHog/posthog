import { FolderSettingsView } from "@posthog/ui/features/settings/FolderSettingsView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/folders/$folderId")({
  component: FolderSettingsView,
});
