import {
  SIDE_CHAT_SERVICE,
  type SideChatService,
  type SideChatThread,
} from "@posthog/core/sessions/sideChatService";
import { useService } from "@posthog/di/react";
import { useCallback } from "react";
import { useStore } from "zustand";

const EMPTY_THREAD: SideChatThread = {
  messages: [],
  isLoading: false,
  hasError: false,
};

export function useSideChat(
  taskId: string,
  mainConversation: string,
): {
  thread: SideChatThread;
  ask: (question: string) => Promise<void>;
} {
  const service = useService<SideChatService>(SIDE_CHAT_SERVICE);
  const thread = useStore(
    service.store,
    (state) => state.threads[taskId] ?? EMPTY_THREAD,
  );
  const ask = useCallback(
    (question: string) => service.ask(taskId, question, mainConversation),
    [mainConversation, service, taskId],
  );

  return { thread, ask };
}
