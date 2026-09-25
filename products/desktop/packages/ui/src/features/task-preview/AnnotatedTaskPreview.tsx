import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { commentAgentContext } from "@posthog/ui/features/sessions/commentAgentContext";
import {
  useCommentsQuery,
  useCreateComment,
} from "@posthog/ui/features/sessions/components/useComments";
import { sendCommentToAgent } from "@posthog/ui/features/sessions/sendCommentToAgent";
import { useCallback, useMemo, useRef, useState } from "react";
import { PreviewCommentThreads } from "./PreviewCommentThreads";
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
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [locateRequest, setLocateRequest] =
    useState<TaskPreviewLocateRequest | null>(null);
  const [pending, setPending] = useState<PendingComment | null>(null);

  const threads = useMemo(
    () => previewThreads(commentsQuery.data ?? []),
    [commentsQuery.data],
  );
  const pins = useMemo(
    () => previewPins(threads, activeThreadId),
    [threads, activeThreadId],
  );

  const selectThread = useCallback((id: string) => {
    setActiveThreadId(id);
    setLocateRequest((current) => ({ id, nonce: (current?.nonce ?? 0) + 1 }));
  }, []);

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
    setActiveThreadId(created.id);
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

  const showThreads = threads.length > 0 || commenting;

  return (
    <div className="@container flex size-full min-h-0">
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
          onActivatePin={selectThread}
        />
        {commenting && (
          <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
            <span className="rounded bg-background px-2 py-1 text-foreground text-xs shadow">
              Click an element to comment on it.
            </span>
          </div>
        )}
      </div>
      {showThreads && (
        <aside className="@[640px]:block hidden w-72 shrink-0 overflow-y-auto border-border border-l">
          <PreviewCommentThreads
            threads={threads}
            target={target}
            taskId={taskId}
            name={title}
            port={port}
            members={members}
            activeThreadId={activeThreadId}
            onSelect={selectThread}
          />
        </aside>
      )}
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
