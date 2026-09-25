import type { CommentTarget } from "@posthog/core/comments/anchors";
import type { UserBasic } from "@posthog/shared/domain-types";
import { CommentThreadCard } from "@posthog/ui/features/sessions/components/CommentThreadCard";
import {
  isOptimisticComment,
  useCreateComment,
  useSetCommentResolved,
} from "@posthog/ui/features/sessions/components/useComments";
import type { PreviewThread } from "./previewComments";

function PreviewThreadRow({
  thread,
  target,
  taskId,
  members,
  selected,
  onSelect,
}: {
  thread: PreviewThread;
  target: CommentTarget;
  taskId: string;
  members: UserBasic[];
  selected: boolean;
  onSelect: () => void;
}) {
  const createComment = useCreateComment(target, taskId);
  const setResolved = useSetCommentResolved(target);
  const pending = isOptimisticComment(thread.root);
  return (
    <CommentThreadCard
      threadId={thread.id}
      entries={thread.entries}
      selected={selected}
      pulsing={false}
      resolved={thread.resolved}
      members={members}
      busy={createComment.isPending || setResolved.isPending}
      source={
        <span className="truncate text-muted-foreground text-xs">
          {thread.number}. {thread.anchor.path}
        </span>
      }
      canReply={!pending}
      canResolve={!pending}
      onSelect={onSelect}
      onReply={async (content, mentions) => {
        await createComment.mutateAsync({
          content,
          sourceCommentId: thread.root.id,
          context: { anchor: thread.anchor, taskId },
          mentions,
        });
      }}
      onResolve={(resolved) =>
        setResolved.mutate({ root: thread.root, resolved })
      }
    />
  );
}

export function PreviewCommentThreads({
  threads,
  target,
  taskId,
  members,
  activeThreadId,
  onSelect,
}: {
  threads: PreviewThread[];
  target: CommentTarget;
  taskId: string;
  members: UserBasic[];
  activeThreadId: string | null;
  onSelect: (id: string) => void;
}) {
  if (threads.length === 0) {
    return (
      <p className="p-3 text-muted-foreground text-xs">
        Select Comment, then click an element on the page to add a comment.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2 p-2">
      {threads.map((thread) => (
        <PreviewThreadRow
          key={thread.id}
          thread={thread}
          target={target}
          taskId={taskId}
          members={members}
          selected={thread.id === activeThreadId}
          onSelect={() => onSelect(thread.id)}
        />
      ))}
    </div>
  );
}
