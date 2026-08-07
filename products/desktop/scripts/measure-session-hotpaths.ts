import { performance } from "node:perf_hooks";
import type { AcpMessage } from "@posthog/shared";
import {
  createContextUsageTracker,
  extractContextUsage,
} from "../packages/core/src/sessions/contextUsage";
import {
  createLatestPlanTracker,
  selectLatestPlan,
} from "../packages/core/src/sessions/sessionService";
import {
  accumulateSessionResources,
  createSessionResourcesTracker,
} from "../packages/ui/src/features/sessions/components/accumulateSessionResources";
import type {
  ConversationItem,
  TurnContext,
} from "../packages/ui/src/features/sessions/components/buildConversationItems";
import { mergeConversationItems } from "../packages/ui/src/features/sessions/components/mergeConversationItems";
import { buildThreadGroups } from "../packages/ui/src/features/sessions/components/new-thread/buildThreadGroups";
import { createIncrementalThreadGrouper } from "../packages/ui/src/features/sessions/components/new-thread/incrementalThreadGrouping";

const COMPLETED_TURNS = readPositiveInt("SESSION_COMPLETED_TURNS", 2_000);
const STREAM_EVENTS = readPositiveInt("SESSION_STREAM_EVENTS", 500);
const TOOLS_PER_TURN = readPositiveInt("SESSION_TOOLS_PER_TURN", 3);

interface Measurement {
  label: string;
  ms: number;
}

function readPositiveInt(name: string, fallback: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const completeContext: TurnContext = {
  toolCalls: new Map(),
  childItems: new Map(),
  turnCancelled: false,
  turnComplete: true,
};

function makeActiveContext(): TurnContext {
  return {
    toolCalls: new Map(),
    childItems: new Map(),
    turnCancelled: false,
    turnComplete: false,
  };
}

function userMessage(id: string): ConversationItem {
  return {
    type: "user_message",
    id,
    content: id,
    timestamp: 1,
  };
}

function toolItem(id: string, turnContext: TurnContext): ConversationItem {
  return {
    type: "session_update",
    id,
    turnContext,
    update: {
      sessionUpdate: "tool_call",
      kind: "read",
      title: "Read",
      status: turnContext.turnComplete ? "completed" : "in_progress",
    },
  };
}

function usageUpdateEvent(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: id,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: "s1",
        update: {
          sessionUpdate: "usage_update",
          used: 50_000,
          size: 200_000,
        },
      },
    },
  };
}

function agentChunkEvent(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: id,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: "s1",
        update: { sessionUpdate: "agent_message_chunk", content: "hello" },
      },
    },
  };
}

function resourcesUsedEvent(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: id,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/resources_used",
      params: {
        sessionId: "s1",
        products: [{ id: "feature_flags", label: "Feature flags" }],
      },
    },
  };
}

function planEvent(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: id,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: "s1",
        update: {
          sessionUpdate: "plan",
          entries: [],
        },
      },
    },
  };
}

function turnEndEvent(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: id,
    message: {
      jsonrpc: "2.0",
      id,
      result: { stopReason: "end_turn" },
    },
  };
}

function measure(label: string, fn: () => void): Measurement {
  fn();
  const start = performance.now();
  fn();
  return { label, ms: performance.now() - start };
}

function buildCompletedThreadItems(): ConversationItem[] {
  const items: ConversationItem[] = [];
  for (let turn = 0; turn < COMPLETED_TURNS; turn++) {
    items.push(userMessage(`u-${turn}`));
    for (let tool = 0; tool < TOOLS_PER_TURN; tool++) {
      items.push(toolItem(`t-${turn}-${tool}`, completeContext));
    }
  }
  return items;
}

function buildThreadSequences(): ConversationItem[][] {
  const base = buildCompletedThreadItems();
  const activeItems: ConversationItem[] = [];
  const sequences: ConversationItem[][] = [base];

  for (let i = 0; i < STREAM_EVENTS; i++) {
    activeItems.push(toolItem(`active-${i}`, makeActiveContext()));
    sequences.push([...base, ...activeItems]);
  }

  return sequences;
}

function buildContextUsageSequences(): AcpMessage[][] {
  const base: AcpMessage[] = [usageUpdateEvent(0)];
  for (let i = 1; i <= COMPLETED_TURNS * TOOLS_PER_TURN; i++) {
    base.push(agentChunkEvent(i));
  }

  const sequences: AcpMessage[][] = [base];
  const streamed: AcpMessage[] = [];
  for (let i = 0; i < STREAM_EVENTS; i++) {
    streamed.push(agentChunkEvent(base.length + i));
    sequences.push([...base, ...streamed]);
  }

  return sequences;
}

function buildResourceSequences(): AcpMessage[][] {
  const base: AcpMessage[] = [];
  for (let i = 0; i <= COMPLETED_TURNS * TOOLS_PER_TURN; i++) {
    base.push(i === 0 ? resourcesUsedEvent(i) : agentChunkEvent(i));
  }

  const sequences: AcpMessage[][] = [base];
  const streamed: AcpMessage[] = [];
  for (let i = 0; i < STREAM_EVENTS; i++) {
    streamed.push(agentChunkEvent(base.length + i));
    sequences.push([...base, ...streamed]);
  }

  return sequences;
}

function buildPlanSequences(): AcpMessage[][] {
  const base: AcpMessage[] = [planEvent(0)];
  for (let i = 1; i <= COMPLETED_TURNS * TOOLS_PER_TURN; i++) {
    base.push(agentChunkEvent(i));
  }
  base.push(turnEndEvent(base.length));

  const sequences: AcpMessage[][] = [base];
  const streamed: AcpMessage[] = [];
  for (let i = 0; i < STREAM_EVENTS; i++) {
    streamed.push(agentChunkEvent(base.length + i));
    sequences.push([...base, ...streamed]);
  }

  return sequences;
}

function runContextUsageBenchmark(): Measurement[] {
  const sequences = buildContextUsageSequences();
  return [
    measure("context usage full scan", () => {
      for (const events of sequences) {
        extractContextUsage(events);
      }
    }),
    measure("context usage append tracker", () => {
      const tracker = createContextUsageTracker();
      for (const events of sequences) {
        tracker.update(events);
      }
    }),
  ];
}

function runSessionResourcesBenchmark(): Measurement[] {
  const sequences = buildResourceSequences();
  return [
    measure("session resources full scan", () => {
      for (const events of sequences) {
        accumulateSessionResources(events);
      }
    }),
    measure("session resources append tracker", () => {
      const tracker = createSessionResourcesTracker();
      for (const events of sequences) {
        tracker.update(events);
      }
    }),
  ];
}

function runLatestPlanBenchmark(): Measurement[] {
  const sequences = buildPlanSequences();
  return [
    measure("latest plan full scan", () => {
      for (const events of sequences) {
        selectLatestPlan(events);
      }
    }),
    measure("latest plan append tracker", () => {
      const tracker = createLatestPlanTracker();
      for (const events of sequences) {
        tracker.update(events);
      }
    }),
  ];
}

function runConversationMergeBenchmark(): Measurement[] {
  const sequences = buildThreadSequences();
  return [
    measure("conversation merge old no-op copy", () => {
      for (const conversationItems of sequences) {
        [...conversationItems];
      }
    }),
    measure("conversation merge no-op fast path", () => {
      for (const conversationItems of sequences) {
        mergeConversationItems({
          conversationItems,
          optimisticItems: [],
          isCloud: false,
        });
      }
    }),
  ];
}

function runThreadGroupingBenchmark(): Measurement[] {
  const sequences = buildThreadSequences();
  const overrides = {};
  return [
    measure("thread grouping full rebuild", () => {
      for (const items of sequences) {
        buildThreadGroups(items, "partial", overrides);
      }
    }),
    measure("thread grouping append tracker", () => {
      const grouper = createIncrementalThreadGrouper();
      for (const items of sequences) {
        grouper.update(items, "partial", overrides);
      }
    }),
  ];
}

function format(ms: number): string {
  return `${ms.toFixed(2)}ms`;
}

function printPair([full, incremental]: Measurement[]) {
  const speedup = full.ms / incremental.ms;
  process.stdout.write(
    `${full.label}: ${format(full.ms)}\n` +
      `${incremental.label}: ${format(incremental.ms)}\n` +
      `speedup: ${speedup.toFixed(1)}x\n\n`,
  );
}

process.stdout.write(
  `Synthetic session: ${COMPLETED_TURNS} completed turns, ` +
    `${TOOLS_PER_TURN} tools/turn, ${STREAM_EVENTS} streamed appends\n\n`,
);
printPair(runContextUsageBenchmark());
printPair(runSessionResourcesBenchmark());
printPair(runLatestPlanBenchmark());
printPair(runConversationMergeBenchmark());
printPair(runThreadGroupingBenchmark());
