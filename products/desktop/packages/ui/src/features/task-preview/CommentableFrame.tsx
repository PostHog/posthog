import {
  type CommentTarget,
  isSameCommentTarget,
} from "@posthog/core/comments/anchors";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import {
  type CommentResource,
  commentAgentContext,
  withScreenshot,
} from "@posthog/ui/features/sessions/commentAgentContext";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import type { HighlightResolution } from "@posthog/ui/features/sessions/components/commentViewTypes";
import {
  useCommentsQuery,
  useCreateComment,
} from "@posthog/ui/features/sessions/components/useComments";
import { sendCommentToAgent } from "@posthog/ui/features/sessions/sendCommentToAgent";
import { showTaskChat } from "@posthog/ui/features/sessions/showTaskChat";
import { toast } from "@posthog/ui/primitives/toast";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { browserCommentPage } from "./browserComments";
import { PickModeBanner } from "./PickModeBanner";
import {
  type PreviewThread,
  previewPathname,
  previewPins,
  previewThreads,
} from "./previewComments";
import { TaskPreviewFrame } from "./TaskPreviewFrame";
import type {
  TaskPreviewLocateRequest,
  TaskPreviewLocation,
  TaskPreviewNavigationRequest,
} from "./taskPreviewFrameHost";
import {
  type PickedElement,
  usePickedElementCard,
} from "./usePickedElementCard";

export type CommentableFrameSurface =
  | { kind: "preview"; port: number; onOpenPage: (path: string) => void }
  | {
      kind: "browser";
      origin: string;
      active: boolean;
      onOpenPage: (url: string) => void;
    };

function isOnPage(
  thread: PreviewThread,
  origin: string | undefined,
  currentPath: string,
): boolean {
  if (origin !== undefined && thread.anchor.origin !== origin) return false;
  return previewPathname(thread.anchor.path) === previewPathname(currentPath);
}

export function CommentableFrame({
  taskId,
  frameId,
  url,
  title,
  target,
  surface,
  commenting,
  chatVisible,
  navigationRequest,
  onLocationChange,
  onCommentingChange,
  onLoadingChange,
  onLoadFailed,
}: {
  taskId: string;
  frameId: string;
  url: string;
  title: string;
  target: CommentTarget;
  surface: CommentableFrameSurface;
  commenting: boolean;
  chatVisible: boolean;
  navigationRequest: TaskPreviewNavigationRequest | null;
  onLocationChange: (location: TaskPreviewLocation) => void;
  onCommentingChange: (commenting: boolean) => void;
  onLoadingChange: (loading: boolean) => void;
  onLoadFailed: () => void;
}) {
  const commentsQuery = useCommentsQuery(target, taskId);
  const createComment = useCreateComment(target, taskId);
  const { members } = useOrgMembers();
  const frameRef = useRef<HTMLDivElement>(null);
  const [locateRequest, setLocateRequest] =
    useState<TaskPreviewLocateRequest | null>(null);
  const [currentPath, setCurrentPath] = useState(url);
  const {
    pending,
    onPicked,
    onTrackedRect,
    dismiss: dismissPending,
  } = usePickedElementCard(frameRef, onCommentingChange);
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const setCommentResolutions = useCommentNavigationStore(
    (state) => state.setCommentResolutions,
  );
  const activeThreadId =
    focus && isSameCommentTarget(focus.target, target) ? focus.threadId : null;
  const origin = surface.kind === "browser" ? surface.origin : undefined;

  const threads = useMemo(
    () => previewThreads(commentsQuery.data ?? []),
    [commentsQuery.data],
  );
  const pins = useMemo(
    () => previewPins(threads, activeThreadId, origin),
    [threads, activeThreadId, origin],
  );

  const openPageRef = useRef(surface.onOpenPage);
  useLayoutEffect(() => {
    openPageRef.current = surface.onOpenPage;
  });
  const openedForNonce = useRef<number | null>(null);
  const followsFocus = surface.kind === "preview" || surface.active;
  useEffect(() => {
    if (!followsFocus) return;
    if (!focus || !activeThreadId || focus.intent !== "navigate") return;
    const thread = threads.find((item) => item.id === activeThreadId);
    if (!thread) return;
    if (!isOnPage(thread, origin, currentPath)) {
      const page =
        surface.kind === "browser"
          ? browserCommentPage(thread.anchor)?.url
          : thread.anchor.path;
      if (!page || openedForNonce.current === focus.nonce) return;
      openedForNonce.current = focus.nonce;
      openPageRef.current(page);
      return;
    }
    setLocateRequest((current) =>
      current?.nonce === focus.nonce
        ? current
        : { id: activeThreadId, nonce: focus.nonce },
    );
  }, [
    followsFocus,
    focus,
    activeThreadId,
    threads,
    origin,
    currentPath,
    surface.kind,
  ]);

  const revealThread = useCallback(
    (id: string) =>
      requestCommentFocus(taskId, target, id, { intent: "reveal-thread" }),
    [requestCommentFocus, taskId, target],
  );

  const onPinsChanged = useCallback(
    (ids: string[]) => {
      const changed = new Set(ids);
      const resolutions = new Map<string, HighlightResolution>(
        pins.map((pin) => [pin.id, changed.has(pin.id) ? "orphaned" : "exact"]),
      );
      setCommentResolutions(target, resolutions);
    },
    [pins, setCommentResolutions, target],
  );

  const anchorOf = (comment: PickedElement) =>
    origin ? { ...comment.anchor, origin } : comment.anchor;

  const submit = async (content: string, mentions: number[]) => {
    if (!pending) return;
    const created = await createComment.mutateAsync({
      content,
      context: { anchor: anchorOf(pending) },
      mentions,
    });
    requestCommentFocus(taskId, target, created.id, { intent: "focus-only" });
  };

  const sendToAgent = (comment: PickedElement, content: string) => {
    const resource: CommentResource =
      surface.kind === "browser"
        ? { kind: "browser", name: title, origin: surface.origin }
        : { kind: "preview", name: title, port: surface.port };
    const context = commentAgentContext(anchorOf(comment), resource);
    void sendCommentToAgent({
      taskId,
      comment: content,
      context: withScreenshot(context, comment.screenshot),
      surface: surface.kind,
      openChat: false,
    }).then(() => {
      if (chatVisible) return;
      toast.success("Added to your message", {
        id: `${surface.kind}-comment-queued-${taskId}`,
        description: "Send it from the chat when you are ready.",
        alwaysShow: true,
        action: {
          label: "Open chat",
          onClick: () => showTaskChat(taskId, { focus: true }),
        },
      });
    });
  };

  return (
    <div className="flex size-full min-h-0">
      <div ref={frameRef} className="relative min-w-0 flex-1">
        <TaskPreviewFrame
          url={url}
          taskId={taskId}
          frameId={frameId}
          session={surface.kind === "browser" ? "browser" : "sandbox"}
          title={title}
          picking={commenting}
          pins={pins}
          locateRequest={locateRequest}
          onLoadingChange={onLoadingChange}
          onLoadFailed={onLoadFailed}
          onPicked={onPicked}
          onPickCancelled={() => onCommentingChange(false)}
          onActivatePin={revealThread}
          onPinsChanged={onPinsChanged}
          navigationRequest={navigationRequest}
          onLocationChange={(location) => {
            setCurrentPath(location.path);
            onLocationChange(location);
          }}
          tracking={!!pending}
          onTrackedRect={onTrackedRect}
        />
        {commenting && (
          <PickModeBanner onCancel={() => onCommentingChange(false)} />
        )}
      </div>
      <SelectionCommentOverlay
        selection={
          pending
            ? {
                text: pending.anchor.text,
                fromLine: 1,
                toLine: 1,
                anchor: pending.position,
              }
            : null
        }
        open={!!pending}
        selectionKey={
          pending
            ? `${pending.anchor.path}:${pending.anchor.selector}`
            : undefined
        }
        filePath={title}
        placeholder="Add a comment…"
        submitLabel="Post comment"
        initiallyExpanded
        members={members}
        onDismiss={dismissPending}
        captureScreenshot={false}
        onSubmit={(_start, _end, content, mentions) =>
          submit(content, mentions ?? [])
        }
        onSendToAgent={
          pending ? (content) => sendToAgent(pending, content) : undefined
        }
      />
    </div>
  );
}
