import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { useAppView } from "@posthog/ui/router/useAppView";
import { createFileRoute } from "@tanstack/react-router";

// Channels-space mirror of the /code/ new-task screen. Renders the same shared
// TaskInput (reading the same prefill) so the page stays single-source; only
// the route entry is duplicated so opening it from the channels sidebar keeps
// the channels chrome. (Per-channel new tasks live at /website/$channelId/new.)
export const Route = createFileRoute("/website/new")({
  component: WebsiteNewTaskRoute,
});

function WebsiteNewTaskRoute() {
  const view = useAppView();

  return (
    <TaskInput
      initialPrompt={view.initialPrompt}
      initialPromptKey={view.taskInputRequestId}
      initialCloudRepository={view.initialCloudRepository}
      initialModel={view.initialModel}
      initialMode={view.initialMode}
      reportAssociation={view.reportAssociation}
      suggestions={CHANNEL_TASK_SUGGESTIONS}
    />
  );
}
