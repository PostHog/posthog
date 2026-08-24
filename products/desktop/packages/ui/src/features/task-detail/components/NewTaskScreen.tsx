import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { useChannelsWorld } from "@posthog/ui/features/canvas/hooks/useChannelsWorld";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { useAppView } from "@posthog/ui/router/useAppView";

/**
 * The unscoped new-task screen, wired to the router's prefill. Two routes reach
 * it: `/new`, and `/` for anyone without the spaces layout, whose landing
 * screen this has always been.
 */
export function NewTaskScreen() {
  const view = useAppView();
  const channelsWorld = useChannelsWorld();

  return (
    <TaskInput
      initialPrompt={view.initialPrompt}
      initialPromptKey={view.taskInputRequestId}
      initialCloudRepository={view.initialCloudRepository}
      initialModel={view.initialModel}
      initialMode={view.initialMode}
      reportAssociation={view.reportAssociation}
      suggestions={channelsWorld ? CHANNEL_TASK_SUGGESTIONS : undefined}
    />
  );
}
