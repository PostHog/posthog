import {
  ArrowClockwise,
  ArrowSquareOut,
  ChatCircle,
  Globe,
} from "@phosphor-icons/react";
import { createBrowserTabId } from "@posthog/core/panels/panelStoreHelpers";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  browserTabLabel,
  originOf,
  resolveBrowserAddress,
} from "./browserAddress";
import { browserCommentTarget } from "./browserComments";
import { useBrowserNavigationStore } from "./browserNavigationStore";
import { CommentableFrame } from "./CommentableFrame";
import { PreviewAddressBar } from "./PreviewAddressBar";
import type {
  TaskPreviewLocation,
  TaskPreviewNavigation,
  TaskPreviewNavigationRequest,
} from "./taskPreviewFrameHost";
import { useTabInMainPanel, useTabIsActive } from "./usePreviewTabInMainPanel";

export function TaskBrowserPanel({
  taskId,
  browserId,
  initialUrl,
}: {
  taskId: string;
  browserId: string;
  initialUrl: string;
}) {
  const [url, setUrl] = useState(initialUrl);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [location, setLocation] = useState<TaskPreviewLocation>({
    path: initialUrl,
    canGoBack: false,
    canGoForward: false,
  });
  const [navigationRequest, setNavigationRequest] =
    useState<TaskPreviewNavigationRequest | null>(null);
  const updateBrowserTab = usePanelLayoutStore(
    (state) => state.updateBrowserTab,
  );
  const chatVisible = !useTabInMainPanel(taskId, createBrowserTabId(browserId));
  const pendingUrl = useRef<string | null>(null);

  const requestNavigation = (request: TaskPreviewNavigation) =>
    setNavigationRequest((current) => ({
      ...request,
      nonce: (current?.nonce ?? 0) + 1,
    }));

  const showUrl = (next: string) => {
    setLocation({ path: next, canGoBack: false, canGoForward: false });
    updateBrowserTab(taskId, browserId, {
      url: next,
      label: browserTabLabel(next),
    });
  };

  const openUrl = (next: string) => {
    pendingUrl.current = null;
    setUrl(next);
    setFailed(false);
    setAttempt((current) => current + 1);
    showUrl(next);
  };

  const navigate = (input: string) => {
    const next = resolveBrowserAddress(input);
    if (!next) return;
    if (!url || failed) {
      openUrl(next);
      return;
    }
    pendingUrl.current = next;
    requestNavigation({ kind: "load", path: next });
  };

  const retry = () => {
    setFailed(false);
    setAttempt((current) => current + 1);
  };

  const reload = () => {
    if (failed) {
      retry();
      return;
    }
    requestNavigation({ kind: "load", path: location.path || url });
  };

  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const openUrlRef = useRef(openUrl);
  openUrlRef.current = openUrl;
  const pageRequest = useBrowserNavigationStore(
    (state) => state.requests[browserId],
  );
  const clearNavigation = useBrowserNavigationStore(
    (state) => state.clearNavigation,
  );
  useEffect(() => {
    if (!pageRequest) return;
    openUrlRef.current(pageRequest.url);
    clearNavigation(browserId, pageRequest.nonce);
  }, [pageRequest, browserId, clearNavigation]);

  const origin = originOf(location.path || url) ?? "";
  const commentTarget = useMemo(() => browserCommentTarget(taskId), [taskId]);
  const active = useTabIsActive(taskId, createBrowserTabId(browserId));
  const surface = useMemo(
    () => ({
      kind: "browser" as const,
      origin,
      active,
      onOpenPage: (page: string) => navigateRef.current(page),
    }),
    [origin, active],
  );

  const onLoadFailed = () => {
    const target = pendingUrl.current;
    pendingUrl.current = null;
    if (target) {
      setUrl(target);
      showUrl(target);
    }
    setFailed(true);
  };

  let body: React.ReactNode;
  if (!url) {
    body = (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Globe size={16} />
          </EmptyMedia>
          <EmptyTitle>Open a page</EmptyTitle>
          <EmptyDescription>
            Type an address above. The agent can use this tab too, and it asks
            you before it uses a new site.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  } else if (failed) {
    body = (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Globe size={16} />
          </EmptyMedia>
          <EmptyTitle>The page didn't load</EmptyTitle>
          <EmptyDescription>
            Check the address and your connection, then try again.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="outline"
            size="default"
            data-attr="task-browser-retry"
            onClick={retry}
          >
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  } else {
    body = (
      <CommentableFrame
        key={attempt}
        taskId={taskId}
        frameId={browserId}
        target={commentTarget}
        surface={surface}
        url={url}
        title={browserTabLabel(location.path || url, location.title)}
        commenting={commenting}
        chatVisible={chatVisible}
        navigationRequest={navigationRequest}
        onLocationChange={(next) => {
          pendingUrl.current = null;
          setLocation(next);
          const changed =
            next.path !== location.path || next.title !== location.title;
          if (next.path && changed) {
            updateBrowserTab(taskId, browserId, {
              url: next.path,
              label: browserTabLabel(next.path, next.title),
            });
          }
        }}
        onCommentingChange={setCommenting}
        onLoadingChange={setLoading}
        onLoadFailed={onLoadFailed}
      />
    );
  }

  return (
    <div className="flex size-full min-h-0 flex-col">
      <ChromeBar
        inset="text"
        actions={
          <>
            {loading && !failed && <Spinner size="sm" label="Loading page" />}
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
                data-attr="task-browser-comment"
                disabled={!url || failed}
                variant={commenting ? "primary" : "default"}
                onClick={() => setCommenting((current) => !current)}
              >
                <ChatCircle size={14} />
              </Button>
            </Tooltip>
            <Tooltip content="Reload page" side="bottom">
              <Button
                size="icon-sm"
                aria-label="Reload page"
                data-attr="task-browser-reload"
                disabled={!url}
                onClick={reload}
              >
                <ArrowClockwise size={14} />
              </Button>
            </Tooltip>
            <Tooltip content="Open in your browser" side="bottom">
              <Button
                size="icon-sm"
                aria-label="Open in your browser"
                data-attr="task-browser-open-external"
                disabled={!url}
                onClick={() => openExternalUrl(location.path || url)}
              >
                <ArrowSquareOut size={14} />
              </Button>
            </Tooltip>
          </>
        }
      >
        <PreviewAddressBar
          location={location}
          disabled={false}
          placeholder="Type an address"
          autoFocus={!url}
          onNavigate={navigate}
          onBack={() => requestNavigation({ kind: "back" })}
          onForward={() => requestNavigation({ kind: "forward" })}
        />
      </ChromeBar>
      <div className="min-h-0 flex-1">{body}</div>
    </div>
  );
}
