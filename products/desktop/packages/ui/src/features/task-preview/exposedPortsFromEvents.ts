import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import {
  type AcpMessage,
  isJsonRpcNotification,
  readMcpToolDescriptor,
} from "@posthog/shared";
import type { TaskRunExposedPort } from "@posthog/shared/domain-types";
import { useMemo, useRef } from "react";

export const EXPOSE_PORT_TOOL = "expose_port";

type ToolCallUpdate = {
  sessionUpdate?: string;
  toolCallId?: string;
  status?: string;
  rawInput?: unknown;
  _meta?: unknown;
};

type ExposedPortState = {
  inputs: Map<string, TaskRunExposedPort>;
  byPort: Map<number, TaskRunExposedPort>;
  result: TaskRunExposedPort[];
};

function readInput(rawInput: unknown): TaskRunExposedPort | null {
  if (!rawInput || typeof rawInput !== "object") return null;
  const { port, name } = rawInput as { port?: unknown; name?: unknown };
  if (typeof port !== "number" || !Number.isInteger(port)) return null;
  return { port, name: typeof name === "string" && name ? name : null };
}

export function createExposedPortTracker() {
  return createAppendOnlyTracker<ExposedPortState, TaskRunExposedPort[]>({
    init: () => ({ inputs: new Map(), byPort: new Map(), result: [] }),
    processEvent: (state, event) => {
      const message = event.message;
      if (!isJsonRpcNotification(message)) return;
      if (message.method !== "session/update") return;
      const update = (message.params as { update?: ToolCallUpdate } | undefined)
        ?.update;
      if (
        !update?.toolCallId ||
        (update.sessionUpdate !== "tool_call" &&
          update.sessionUpdate !== "tool_call_update")
      ) {
        return;
      }
      if (readMcpToolDescriptor(update._meta)?.tool === EXPOSE_PORT_TOOL) {
        const input = readInput(update.rawInput);
        if (input) state.inputs.set(update.toolCallId, input);
      }
      const input = state.inputs.get(update.toolCallId);
      if (update.status !== "completed" || !input) return;
      state.byPort.set(input.port, input);
      state.result = [...state.byPort.values()];
    },
    getResult: (state) => state.result,
  });
}

export function exposedPortsFromEvents(
  events: AcpMessage[],
): TaskRunExposedPort[] {
  return createExposedPortTracker().update(events);
}

export function useExposedPortsFromEvents(
  events: AcpMessage[],
): TaskRunExposedPort[] {
  const trackerRef = useRef<ReturnType<typeof createExposedPortTracker> | null>(
    null,
  );
  trackerRef.current ??= createExposedPortTracker();
  const tracker = trackerRef.current;
  return useMemo(() => tracker.update(events), [events, tracker]);
}
