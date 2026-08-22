import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { useAppView } from "@posthog/ui/router/useAppView";
import { createFileRoute } from "@tanstack/react-router";

// The one new-task screen. What used to be three entries (/code, /website/new,
// /website/$channelId/new) renders here: the space rides as `?channel=` (the
// legacy channel-scoped URLs redirect into it), and the channels-space
// suggestions are part of the same prefill.
export const Route = createFileRoute("/_channels/new")({
  component: NewTaskRoute,
  validateSearch: (search: Record<string, unknown>): { channel?: string } => ({
    channel: typeof search.channel === "string" ? search.channel : undefined,
  }),
});

function NewTaskRoute() {
  const { channel } = Route.useSearch();
  const channelsLayout = useChannelsLayout();
  const view = useAppView();

  return (
    <TaskInput
      initialPrompt={view.initialPrompt}
      initialPromptKey={view.taskInputRequestId}
      initialCloudRepository={view.initialCloudRepository}
      initialModel={view.initialModel}
      initialMode={view.initialMode}
      reportAssociation={view.reportAssociation}
      channelId={channel}
      suggestions={channelsLayout ? CHANNEL_TASK_SUGGESTIONS : undefined}
    />
  );
}
