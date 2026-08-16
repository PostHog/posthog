import { PI_SESSION_CONTROLLER } from "@posthog/core/pi-runtime/identifiers";
import type { PiSessionController } from "@posthog/core/pi-runtime/piSessionController";
import { useService } from "@posthog/di/react";
import type { AgentConversationEvent } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  buildAgentConversationItems,
  buildConversationItems,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { useSessionForTask } from "@posthog/ui/features/sessions/sessionStore";
import { type FormEvent, useMemo, useState } from "react";
import { useStore } from "zustand";
import { SideChatView } from "./SideChatView";
import { buildSideChatMainContext } from "./sideChatContext";
import { useSideChat } from "./useSideChat";

const EMPTY_PI_EVENTS: AgentConversationEvent[] = [];

export interface SideChatPanelProps {
  taskId: string;
  task: Task;
}

export function SideChatPanel({ taskId, task }: SideChatPanelProps) {
  const piSessionController = useService<PiSessionController>(
    PI_SESSION_CONTROLLER,
  );
  const piEvents = useStore(
    piSessionController.store,
    (state) => state.sessions[taskId]?.events ?? EMPTY_PI_EVENTS,
  );
  const acpSession = useSessionForTask(taskId);
  const conversationItems = useMemo(
    () =>
      task.runtime === "pi"
        ? buildAgentConversationItems(piEvents, false).items
        : buildConversationItems(
            acpSession?.events ?? [],
            acpSession?.isPromptPending ?? null,
          ).items,
    [acpSession?.events, acpSession?.isPromptPending, piEvents, task.runtime],
  );
  const mainConversation = useMemo(
    () => buildSideChatMainContext(task.description, conversationItems),
    [conversationItems, task.description],
  );
  const { thread, ask } = useSideChat(taskId, mainConversation);
  const [question, setQuestion] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const value = question.trim();
    if (!value || thread.isLoading) return;
    setQuestion("");
    void ask(value);
  };

  return (
    <SideChatView
      taskId={taskId}
      thread={thread}
      question={question}
      onQuestionChange={setQuestion}
      onSubmit={handleSubmit}
    />
  );
}
