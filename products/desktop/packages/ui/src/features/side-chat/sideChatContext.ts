import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";

const MAX_CONTEXT_CHARS = 40_000;

type ConversationTurn = {
  role: "User" | "Assistant";
  content: string;
};

export function buildSideChatMainContext(
  taskDescription: string,
  items: ConversationItem[],
): string {
  const turns: ConversationTurn[] = [];

  const append = (role: ConversationTurn["role"], content: string): void => {
    const normalized = content.trim();
    if (!normalized) return;
    const previous = turns.at(-1);
    if (previous?.role === role) {
      previous.content = `${previous.content}\n${normalized}`;
    } else {
      turns.push({ role, content: normalized });
    }
  };

  for (const item of items) {
    if (item.type === "user_message") {
      append("User", item.content);
    } else if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "agent_message_chunk" &&
      item.update.content.type === "text"
    ) {
      append("Assistant", item.update.content.text);
    }
  }

  const taskContext = taskDescription.trim()
    ? `Task: ${taskDescription.trim()}\n\n`
    : "";
  const context = `${taskContext}${turns
    .map((turn) => `${turn.role}: ${turn.content}`)
    .join("\n\n")}`;

  return context.length <= MAX_CONTEXT_CHARS
    ? context
    : `[Earlier context omitted.]\n${context.slice(-MAX_CONTEXT_CHARS)}`;
}
