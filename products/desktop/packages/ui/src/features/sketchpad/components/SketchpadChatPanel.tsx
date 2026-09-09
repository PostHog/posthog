import {
  ArrowUpIcon,
  ChatCircleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import {
  Button,
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@posthog/quill";
import type { SketchpadSnapshot } from "@posthog/shared";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { SketchpadPanel } from "@posthog/ui/features/sketchpad/components/SketchpadPanel";
import { useStartSketchpadSession } from "@posthog/ui/features/sketchpad/hooks/useStartSketchpadSession";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { setTaskForSketchpad } from "../hooks/useSketchpadTaskLinkStore";
import { CHAT_EXAMPLES } from "../sketchpadCopy";

export interface SketchpadChatPanelProps {
  sketchpadId: string;
  sketchpadName: string;
  snapshot: SketchpadSnapshot;
  headSeq: number;
  taskId: string | undefined;
  onClose: () => void;
}

export function SketchpadChatPanel({
  sketchpadId,
  sketchpadName,
  snapshot,
  headSeq,
  taskId,
  onClose,
}: SketchpadChatPanelProps) {
  return (
    <SketchpadPanel
      title="Agent"
      closeLabel="Close the agent panel"
      onClose={onClose}
      actions={
        taskId ? (
          <Button
            variant="link-muted"
            size="sm"
            onClick={() => setTaskForSketchpad(sketchpadId, undefined)}
          >
            New session
          </Button>
        ) : null
      }
    >
      {taskId ? (
        <SketchpadChatSession taskId={taskId} />
      ) : (
        <SketchpadChatStarter
          sketchpadId={sketchpadId}
          sketchpadName={sketchpadName}
          snapshot={snapshot}
          headSeq={headSeq}
        />
      )}
    </SketchpadPanel>
  );
}

function SketchpadChatSession({ taskId }: { taskId: string }) {
  const { data: task, isPending, refetch } = useQuery(taskDetailQuery(taskId));

  if (isPending) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  if (!task) {
    return (
      <Button variant="link-muted" onClick={() => void refetch()}>
        Could not load this session. Retry
      </Button>
    );
  }

  return (
    <div className="min-h-0 flex-1">
      <EmbeddedSessionView task={task} />
    </div>
  );
}

function SketchpadChatStarter({
  sketchpadId,
  sketchpadName,
  snapshot,
  headSeq,
}: {
  sketchpadId: string;
  sketchpadName: string;
  snapshot: SketchpadSnapshot;
  headSeq: number;
}) {
  const [prompt, setPrompt] = useState("");
  const { start, pending } = useStartSketchpadSession({
    sketchpadId,
    sketchpadName,
    snapshot,
    headSeq,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
        <span className="flex size-10 items-center justify-center rounded-full bg-(--accent-a3) text-(--accent-11)">
          <ChatCircleIcon size={19} />
        </span>
        <div className="flex flex-col gap-1">
          <p className="font-semibold text-[13px]">Build with the agent</p>
          <p className="text-(--gray-11) text-[12px] leading-relaxed">
            Describe what you want on this board. The agent adds fragments as it
            works.
          </p>
        </div>
        <div className="flex w-full flex-col gap-1.5">
          {CHAT_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="rounded-(--radius-2) border border-(--gray-4) px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-(--gray-3)"
              onClick={() => setPrompt(example)}
            >
              {example}
            </button>
          ))}
        </div>
      </div>
      <div className="shrink-0 border-(--gray-4) border-t p-3">
        <InputGroup>
          <InputGroupTextarea
            value={prompt}
            placeholder="Ask for a fragment"
            className="min-h-[52px] resize-none text-[13px]"
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void start(prompt);
              }
            }}
          />
          <InputGroupAddon align="block-end">
            <InputGroupButton
              className="ml-auto"
              size="icon-sm"
              variant="primary"
              aria-label="Start"
              disabled={pending || prompt.trim().length === 0}
              onClick={() => void start(prompt)}
            >
              {pending ? (
                <SpinnerGapIcon size={14} className="animate-spin" />
              ) : (
                <ArrowUpIcon size={14} />
              )}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </div>
  );
}
