import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import { buildSideChatMainContext } from "./sideChatContext";

describe("buildSideChatMainContext", () => {
  it("includes user and assistant messages without agent thoughts or status rows", () => {
    const items = [
      {
        type: "user_message",
        id: "user-1",
        content: "Can you inspect the plan?",
        timestamp: 1,
      },
      {
        type: "session_update",
        id: "thought-1",
        update: {
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "Private reasoning" },
        },
        turnContext: {},
      },
      {
        type: "session_update",
        id: "assistant-1",
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "The plan has three steps." },
        },
        turnContext: {},
      },
      {
        type: "session_update",
        id: "status-1",
        update: { sessionUpdate: "status", status: "working" },
        turnContext: {},
      },
    ] as unknown as ConversationItem[];

    expect(buildSideChatMainContext("Refine the rollout plan", items)).toBe(
      "Task: Refine the rollout plan\n\nUser: Can you inspect the plan?\n\nAssistant: The plan has three steps.",
    );
  });
});
