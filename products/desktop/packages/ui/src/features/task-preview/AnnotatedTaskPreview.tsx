import {
  type ElementCommentAnchor,
  isSameCommentTarget,
} from "@posthog/core/comments/anchors";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { commentAgentContext } from "@posthog/ui/features/sessions/commentAgentContext";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import {
  useCommentsQuery,
  useCreateComment,
} from "@posthog/ui/features/sessions/components/useComments";
import { sendCommentToAgent } from "@posthog/ui/features/sessions/sendCommentToAgent";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { previewPins, previewThreads } from "./previewComments";
import { previewCommentTarget } from "./previewCommentTarget";
import { TaskPreviewFrame } from "./TaskPreviewFrame";
import type {
  TaskPreviewElement,
  TaskPreviewLocateRequest,
  TaskPreviewRect,
} from "./taskPreviewFrameHost";

type PendingComment = {
  element: TaskPreviewElement;
  screenshot: string | null;
  anchor: { top: number; right: number; bottom: number };
};

export function AnnotatedTaskPreview({
  taskId,
  port,
  url,
  title,
  commenting,
  onCommentingChange,
  onLoadFailed,
}: {
  taskId: string;
  port: number;
  url: string;
  title: string;
  commenting: boolean;
  onCommentingChange: (commenting: boolean) => void;
  onLoadFailed: () => void;
}) {
  const target = useMemo(
    () => previewCommentTarget(taskId, port),
    [taskId, port],
  );
  const commentsQuery = useCommentsQuery(target, taskId);
  const createComment = useCreateComment(target, taskId);
  const { members } = useOrgMembers();
  const frameRef = useRef<HTMLDivElement>(null);
  const [locateRequest, setLocateRequest] =
    useState<TaskPreviewLocateRequest | null>(null);
  const [pending, setPending] = useState<PendingComment | null>(null);
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const activeThreadId =
    focus && isSameCommentTarget(focus.target, target) ? focus.threadId : null;

  const threads = useMemo(
    () => previewThreads(commentsQuery.data ?? []),
    [commentsQuery.data],
  );
  const pins = useMemo(
    () => previewPins(threads, activeThreadId),
    [threads, activeThreadId],
  );

  useEffect(() => {
    if (!focus || !activeThreadId || focus.intent !== "navigate") return;
    if (!threads.some((thread) => thread.id === activeThreadId)) return;
    setLocateRequest((current) =>
      current?.nonce === focus.nonce
        ? current
        : { id: activeThreadId, nonce: focus.nonce },
    );
  }, [focus, activeThreadId, threads]);

  const revealThread = useCallback(
    (id: string) =>
      requestCommentFocus(taskId, target, id, { intent: "reveal-thread" }),
    [requestCommentFocus, taskId, target],
  );

  const onPicked = useCallback(
    (
      element: TaskPreviewElement,
      rect: TaskPreviewRect,
      screenshot: string | null,
    ) => {
      onCommentingChange(false);
      const box = frameRef.current?.getBoundingClientRect();
      if (!box) return;
      setPending({
        element,
        screenshot,
        anchor: {
          top: box.top + rect.top,
          right: box.left + rect.right,
          bottom: box.top + rect.bottom,
        },
      });
    },
    [onCommentingChange],
  );

  const dismissPending = useCallback(() => setPending(null), []);

  const submit = async (content: string, mentions: number[]) => {
    if (!pending) return;
    const anchor: ElementCommentAnchor = {
      kind: "element",
      ...pending.element,
    };
    const created = await createComment.mutateAsync({
      content,
      context: { anchor },
      mentions,
    });
    requestCommentFocus(taskId, target, created.id, { intent: "focus-only" });
  };

  const sendToAgent = (
    anchor: ElementCommentAnchor,
    screenshot: string | null,
    content: string,
  ) => {
    const context = commentAgentContext(anchor, {
      kind: "preview",
      name: title,
      port,
    });
    void sendCommentToAgent({
      taskId,
      comment: content,
      context: context && screenshot ? { ...context, screenshot } : context,
      surface: "preview",
    });
  };

  return (
    <div className="flex size-full min-h-0">
      <div ref={frameRef} className="relative min-w-0 flex-1">
        <TaskPreviewFrame
          url={url}
          title={title}
          picking={commenting}
          pins={pins}
          locateRequest={locateRequest}
          onLoadFailed={onLoadFailed}
          onPicked={onPicked}
          onPickCancelled={() => onCommentingChange(false)}
          onActivatePin={revealThread}
        />
        {commenting && (
          <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
            <span className="rounded bg-background px-2 py-1 text-foreground text-xs shadow">
              Click an element to comment on it.
            </span>
          </div>
        )}
      </div>
      <SelectionCommentOverlay
        selection={
          pending
            ? {
                text: pending.element.text,
                fromLine: 1,
                toLine: 1,
                anchor: {
                  top: pending.anchor.top,
                  endX: pending.anchor.right,
                  bottom: pending.anchor.bottom,
                },
              }
            : null
        }
        open={!!pending}
        filePath={title}
        placeholder="Add a comment…"
        initiallyExpanded
        members={members}
        onDismiss={dismissPending}
        onSubmit={(_start, _end, content, mentions) =>
          submit(content, mentions ?? [])
        }
        onSendToAgent={
          pending
            ? (content) =>
                sendToAgent(
                  { kind: "element", ...pending.element },
                  pending.screenshot,
                  content,
                )
            : undefined
        }
      />
    </div>
  );
}
