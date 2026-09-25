import { ArrowClockwise, ArrowSquareOut, Globe } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useEffect, useState } from "react";
import { type PreviewProblem, previewProblem } from "./previewProblem";
import { TaskPreviewFrame } from "./TaskPreviewFrame";
import { useTaskPreviewSession } from "./useTaskPreviewSession";

interface TaskPreviewPanelProps {
  taskId: string;
  runId: string;
  port: number;
  label: string;
}

function problemCopy(
  problem: PreviewProblem,
  port: number,
): { title: string; description: string } {
  switch (problem) {
    case "not_ready":
      return {
        title: "This preview isn't ready yet",
        description: `The agent hasn't shared port ${port} in the current sandbox. Ask the agent to start the server, then try again.`,
      };
    case "ended":
      return {
        title: "This preview has ended",
        description:
          "The sandbox stopped. Send the agent a message to start a new sandbox, then open the preview again.",
      };
    case "unavailable":
      return {
        title: "The server isn't answering",
        description: `Nothing answers on port ${port}. The server can still be starting. Try again in a moment.`,
      };
    case "load_failed":
      return {
        title: "The preview didn't load",
        description: "Try again in a moment.",
      };
    case "error":
      return {
        title: "Couldn't start the preview",
        description: "Check your connection, then try again.",
      };
  }
}

export function TaskPreviewPanel({
  taskId,
  runId,
  port,
  label,
}: TaskPreviewPanelProps) {
  const [attempt, setAttempt] = useState(0);
  const [failedAttempt, setFailedAttempt] = useState<number | null>(null);
  const session = useTaskPreviewSession(taskId, runId, port, attempt);
  const outcome = session.data?.outcome;
  const url = outcome === "ready" ? session.data?.url : null;

  useEffect(() => {
    if (outcome) {
      track(ANALYTICS_EVENTS.TASK_PREVIEW_SESSION_STARTED, { outcome });
    }
  }, [outcome]);

  const retry = () => setAttempt((current) => current + 1);
  const openInBrowser = () => {
    if (!url) return;
    track(ANALYTICS_EVENTS.TASK_PREVIEW_OPENED_IN_BROWSER);
    openExternalUrl(url);
  };

  const problem = previewProblem({
    session: session.data,
    isError: session.isError,
    loadFailed: failedAttempt === attempt,
  });

  let body: React.ReactNode;
  if (session.isLoading) {
    body = <LoadingState label="Starting preview" />;
  } else if (problem) {
    const copy = problemCopy(problem, port);
    body = (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Globe size={16} />
          </EmptyMedia>
          <EmptyTitle>{copy.title}</EmptyTitle>
          <EmptyDescription>{copy.description}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="outline"
            size="default"
            disabled={session.isFetching}
            onClick={retry}
          >
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  } else if (url) {
    body = (
      <TaskPreviewFrame
        key={attempt}
        url={url}
        title={`Preview of ${label}`}
        onLoadFailed={() => setFailedAttempt(attempt)}
      />
    );
  }

  return (
    <div className="flex size-full min-h-0 flex-col">
      <ChromeBar
        inset="text"
        actions={
          <>
            <Tooltip content="Reload preview" side="bottom">
              <Button
                size="icon-sm"
                aria-label="Reload preview"
                data-attr="task-preview-reload"
                disabled={session.isFetching}
                onClick={retry}
              >
                <ArrowClockwise size={14} />
              </Button>
            </Tooltip>
            <Tooltip content="Open in browser" side="bottom">
              <Button
                size="icon-sm"
                aria-label="Open in browser"
                data-attr="task-preview-open-in-browser"
                disabled={!url}
                onClick={openInBrowser}
              >
                <ArrowSquareOut size={14} />
              </Button>
            </Tooltip>
          </>
        }
      >
        <span className="min-w-0 truncate text-foreground text-xs">
          {label}
        </span>
        <span className="shrink-0 text-muted-foreground text-xs">:{port}</span>
      </ChromeBar>
      <div className="min-h-0 flex-1">{body}</div>
    </div>
  );
}
