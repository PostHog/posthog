import {
  ArrowClockwise,
  ArrowSquareOut,
  ChatCircle,
  Globe,
  SquareSplitHorizontal,
} from "@phosphor-icons/react";
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
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useEffect, useMemo, useRef, useState } from "react";
import { CommentableFrame } from "./CommentableFrame";
import { PreviewAddressBar } from "./PreviewAddressBar";
import { previewCommentTarget } from "./previewCommentTarget";
import { resolvePreviewNavigation } from "./previewNavigation";
import { type PreviewProblem, previewProblem } from "./previewProblem";
import type {
  TaskPreviewLocation,
  TaskPreviewNavigation,
  TaskPreviewNavigationRequest,
} from "./taskPreviewFrameHost";
import { usePreviewTabInMainPanel } from "./usePreviewTabInMainPanel";
import { useTaskPreviewAnnotationsSupported } from "./useTaskPreviewAnnotationsSupported";
import { useTaskPreviewSession } from "./useTaskPreviewSession";

interface TaskPreviewPanelProps {
  taskId: string;
  runId: string;
  local: boolean;
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
        description:
          "The server might still be starting. Try again in a moment.",
      };
    case "load_failed":
      return {
        title: "The preview didn't load",
        description: `The page on port ${port} didn't respond. Check that the server is running, then try again.`,
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
  local,
  port,
  label,
}: TaskPreviewPanelProps) {
  const [attempt, setAttempt] = useState(0);
  const [failedAttempt, setFailedAttempt] = useState<number | null>(null);
  const [commenting, setCommenting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [location, setLocation] = useState<TaskPreviewLocation>({
    path: "/",
    canGoBack: false,
    canGoForward: false,
  });
  const [navigationRequest, setNavigationRequest] =
    useState<TaskPreviewNavigationRequest | null>(null);
  const annotationsSupported = useTaskPreviewAnnotationsSupported();
  const inMainPanel = usePreviewTabInMainPanel(taskId, runId, port);
  const commentTarget = useMemo(
    () => previewCommentTarget(taskId, port),
    [taskId, port],
  );
  const openPreviewTab = usePanelLayoutStore((state) => state.openPreviewTab);
  const remoteSession = useTaskPreviewSession(
    taskId,
    runId,
    port,
    attempt,
    !local,
  );
  const session = local
    ? {
        data: { outcome: "ready" as const, url: `http://localhost:${port}/` },
        isLoading: false,
        isError: false,
        isFetching: false,
      }
    : remoteSession;
  const outcome = session.data?.outcome;
  const url = outcome === "ready" ? session.data?.url : null;

  useEffect(() => {
    if (outcome) {
      track(ANALYTICS_EVENTS.TASK_PREVIEW_SESSION_STARTED, { outcome });
    }
  }, [outcome]);

  const retry = () => setAttempt((current) => current + 1);
  const requestNavigation = (request: TaskPreviewNavigation) =>
    setNavigationRequest((current) => ({
      ...request,
      nonce: (current?.nonce ?? 0) + 1,
    }));
  const navigate = (input: string) => {
    if (!url) return;
    const target = resolvePreviewNavigation(input, url, location.path);
    if (!target) return;
    if (target.kind === "external") {
      openExternalUrl(target.url);
      return;
    }
    requestNavigation(target);
  };
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const surface = useMemo(
    () => ({
      kind: "preview" as const,
      port,
      onOpenPage: (path: string) => navigateRef.current(path),
    }),
    [port],
  );
  const openSideBySide = () => {
    track(ANALYTICS_EVENTS.TASK_PREVIEW_OPENED, {
      source: "preview_tab",
      placement: "split",
    });
    openPreviewTab(taskId, { runId, port, label }, "split");
  };
  const openInBrowser = () => {
    if (!url || !local) return;
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
            data-attr="task-preview-retry"
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
      <CommentableFrame
        key={attempt}
        taskId={taskId}
        frameId={`preview-${taskId}-${port}`}
        target={commentTarget}
        surface={surface}
        url={url}
        title={`Preview of ${label}`}
        commenting={commenting}
        chatVisible={!inMainPanel}
        navigationRequest={navigationRequest}
        onLocationChange={setLocation}
        onCommentingChange={setCommenting}
        onLoadingChange={setLoading}
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
            {loading && !problem && <Spinner size="sm" label="Loading page" />}
            {annotationsSupported && (
              <Tooltip
                content={commenting ? "Stop commenting" : "Comment on the page"}
                side="bottom"
              >
                <Button
                  size="icon-sm"
                  aria-label={
                    commenting ? "Stop commenting" : "Comment on the page"
                  }
                  aria-pressed={commenting}
                  data-attr="task-preview-comment"
                  disabled={!url}
                  variant={commenting ? "primary" : "default"}
                  onClick={() => setCommenting((current) => !current)}
                >
                  <ChatCircle size={14} />
                </Button>
              </Tooltip>
            )}
            {inMainPanel && (
              <Tooltip content="Open side by side" side="bottom">
                <Button
                  size="icon-sm"
                  aria-label="Open side by side"
                  data-attr="task-preview-open-side-by-side"
                  onClick={openSideBySide}
                >
                  <SquareSplitHorizontal size={14} />
                </Button>
              </Tooltip>
            )}
            <Tooltip content="Reload page" side="bottom">
              <Button
                size="icon-sm"
                aria-label="Reload page"
                data-attr="task-preview-reload"
                disabled={session.isFetching}
                onClick={retry}
              >
                <ArrowClockwise size={14} />
              </Button>
            </Tooltip>
            {local && (
              <Tooltip content="Open in your browser" side="bottom">
                <Button
                  size="icon-sm"
                  aria-label="Open in your browser"
                  data-attr="task-preview-open-in-browser"
                  disabled={!url}
                  onClick={openInBrowser}
                >
                  <ArrowSquareOut size={14} />
                </Button>
              </Tooltip>
            )}
          </>
        }
      >
        <PreviewAddressBar
          label={label}
          port={port}
          location={location}
          disabled={!url}
          onNavigate={navigate}
          onBack={() => requestNavigation({ kind: "back" })}
          onForward={() => requestNavigation({ kind: "forward" })}
        />
      </ChromeBar>
      <div className="min-h-0 flex-1">{body}</div>
    </div>
  );
}
