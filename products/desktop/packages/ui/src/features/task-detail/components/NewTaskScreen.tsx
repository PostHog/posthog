import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { NewSessionHeading } from "@posthog/ui/features/canvas/components/work/NewSessionHeading";
import { useChannelsWorld } from "@posthog/ui/features/canvas/hooks/useChannelsWorld";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { getTaskInputSessionId } from "@posthog/ui/features/task-detail/taskInputSession";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { navigateToChannelNewTask } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useRouterState } from "@tanstack/react-router";

/**
 * The unscoped new-task screen, wired to the router's prefill. Two routes reach
 * it: `/new`, and `/` for anyone without the spaces layout, whose landing
 * screen this has always been. Under the Work layout it is what every new tab
 * opens on, headed by a space picker: choosing one moves to that space's own
 * new-session route.
 */
export function NewTaskScreen() {
  const view = useAppView();
  const channelsWorld = useChannelsWorld();
  const workLayout = useWorkLayout();
  const tabId = useRouterState({
    select: (state) => state.location.state.tabId,
  });
  const sessionId = getTaskInputSessionId(tabId);
  // Nothing to name in the chrome bar: the headline is the page's title.
  useSetHeaderContent(null, workLayout);

  if (!tabId) return null;

  return (
    <TaskInput
      key={sessionId}
      sessionId={sessionId}
      initialPrompt={view.initialPrompt}
      initialContent={view.initialContent}
      recoveredFromKey={view.recoveredFromKey}
      initialPromptKey={view.taskInputRequestId}
      initialCloudRepository={view.initialCloudRepository}
      initialModel={view.initialModel}
      initialMode={view.initialMode}
      reportAssociation={view.reportAssociation}
      suggestions={channelsWorld ? CHANNEL_TASK_SUGGESTIONS : undefined}
      heading={
        workLayout ? (
          <NewSessionHeading
            channelId={null}
            onChangeSpace={navigateToChannelNewTask}
          />
        ) : undefined
      }
    />
  );
}
