import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { exposedPortsFromEvents } from "./exposedPortsFromEvents";

function toolUpdate(
  toolCallId: string,
  fields: Record<string, unknown>,
  tool = "expose_port",
): AcpMessage {
  return {
    type: "acp_message",
    ts: 0,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "tool_call_update",
          toolCallId,
          _meta: { posthog: { mcp: { server: "posthog-code-tools", tool } } },
          ...fields,
        },
      },
    },
  } as unknown as AcpMessage;
}

describe("exposedPortsFromEvents", () => {
  it("keeps each completed port once, with its latest name", () => {
    const events = [
      toolUpdate("a", { rawInput: { port: 5173, name: "Web" } }),
      toolUpdate("a", { status: "completed" }),
      toolUpdate("b", { rawInput: { port: 3000 } }),
      toolUpdate("b", { status: "failed" }),
      toolUpdate("c", { rawInput: { port: 8000 } }, "upload_artifact"),
      toolUpdate("c", { status: "completed" }),
      toolUpdate("d", { rawInput: { port: 5173, name: "Web app" } }),
      toolUpdate("d", { status: "completed" }),
    ];

    expect(exposedPortsFromEvents(events)).toEqual([
      { port: 5173, name: "Web app" },
    ]);
  });
});
