import {
  PI_QUEUE_MODES,
  PI_THINKING_LEVELS,
  type PiCommand,
  type PiModelOption,
  type PiSessionStatus,
} from "@posthog/agent/pi/types";
import { z } from "zod";

const agentContent = z.discriminatedUnion("type", [
  z.object({ type: z.literal("text"), text: z.string() }),
  z.object({
    type: z.literal("image"),
    data: z.string(),
    mimeType: z.string(),
  }),
  z.object({
    type: z.literal("audio"),
    data: z.string(),
    mimeType: z.string(),
  }),
  z.object({
    type: z.literal("resource_link"),
    uri: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    mimeType: z.string().nullable().optional(),
    size: z.number().nullable().optional(),
    title: z.string().nullable().optional(),
  }),
  z.object({
    type: z.literal("resource"),
    resource: z.union([
      z.object({
        uri: z.string(),
        mimeType: z.string().nullable().optional(),
        text: z.string(),
      }),
      z.object({
        uri: z.string(),
        mimeType: z.string().nullable().optional(),
        blob: z.string(),
      }),
    ]),
  }),
]);

const agentToolContent = z.discriminatedUnion("type", [
  z.object({ type: z.literal("content"), content: agentContent }),
  z.object({
    type: z.literal("diff"),
    path: z.string(),
    oldText: z.string().nullable().optional(),
    newText: z.string(),
  }),
  z.object({ type: z.literal("terminal"), terminalId: z.string() }),
]);

const agentToolCall = z.object({
  id: z.string(),
  title: z.string(),
  kind: z
    .enum([
      "read",
      "edit",
      "delete",
      "move",
      "search",
      "execute",
      "think",
      "fetch",
      "switch_mode",
      "question",
      "other",
    ])
    .nullable()
    .optional(),
  status: z
    .enum(["pending", "in_progress", "completed", "failed"])
    .nullable()
    .optional(),
  content: z.array(agentToolContent).optional(),
  locations: z
    .array(
      z.object({ path: z.string(), line: z.number().nullable().optional() }),
    )
    .optional(),
  rawInput: z.unknown().optional(),
  rawOutput: z.unknown().optional(),
  parentId: z.string().optional(),
});

export const piConversationEvent = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("user_message"),
    id: z.string(),
    timestamp: z.number(),
    content: z.array(agentContent),
  }),
  z.object({
    type: z.literal("assistant_message_chunk"),
    timestamp: z.number(),
    content: agentContent,
  }),
  z.object({
    type: z.literal("assistant_thought_chunk"),
    timestamp: z.number(),
    content: agentContent,
  }),
  z.object({
    type: z.literal("tool_call_started"),
    timestamp: z.number(),
    toolCall: agentToolCall,
  }),
  z.object({
    type: z.literal("tool_call_updated"),
    timestamp: z.number(),
    toolCall: agentToolCall.partial().required({ id: true }),
  }),
  z.object({
    type: z.literal("runtime_status"),
    timestamp: z.number(),
    status: z.string(),
    isComplete: z.boolean().optional(),
    error: z.string().optional(),
    message: z.string().optional(),
    attempt: z.number().optional(),
    maxAttempts: z.number().optional(),
    delayMs: z.number().optional(),
  }),
  z.object({
    type: z.literal("runtime_error"),
    timestamp: z.number(),
    errorType: z.string(),
    message: z.string(),
  }),
  z.object({
    type: z.literal("turn_completed"),
    timestamp: z.number(),
    stopReason: z.string().optional(),
  }),
]);

export const piConversationOutput = z.array(piConversationEvent);

export const piImageContent = z.object({
  type: z.literal("image"),
  data: z.string(),
  mimeType: z.string(),
});

export const startPiSessionInput = z.object({
  taskId: z.string(),
  cwd: z.string(),
  prompt: z.string(),
  model: z.string().optional(),
});

export const piSessionStartOutput = z.object({
  sessionFile: z.string().nullable(),
  sessionId: z.string(),
});

export const piSessionHealthOutput = z.object({
  state: z.enum(["cold", "starting", "idle", "streaming"]),
  pid: z.number().optional(),
  lastUsedAt: z.number().optional(),
});

export const piSessionVoidOutput = z.void();

export const piSessionCancelledOutput = z.object({ cancelled: z.boolean() });

export const piSessionModelOutput = z.object({
  provider: z.string(),
  id: z.string(),
});

export const piThinkingLevel = z.enum(PI_THINKING_LEVELS);
export const piQueueMode = z.enum(PI_QUEUE_MODES);

export const piSessionCycleModelOutput = z
  .object({
    model: piSessionModelOutput,
    thinkingLevel: piThinkingLevel,
    isScoped: z.boolean(),
  })
  .nullable();

export const piSessionAvailableModelsOutput = z.array(
  piSessionModelOutput.extend({
    contextWindow: z.number(),
    reasoning: z.boolean(),
    thinkingLevels: z.array(piThinkingLevel),
  }),
) satisfies z.ZodType<PiModelOption[]>;

export const piSessionThinkingCycleOutput = z
  .object({ level: piThinkingLevel })
  .nullable();

export const piSessionStatusOutput = z.object({
  model: piSessionModelOutput.optional(),
  thinkingLevel: piThinkingLevel,
  isStreaming: z.boolean(),
  isCompacting: z.boolean(),
  steeringMode: piQueueMode,
  followUpMode: piQueueMode,
  sessionFile: z.string().optional(),
  sessionId: z.string(),
  sessionName: z.string().optional(),
  autoCompactionEnabled: z.boolean(),
  messageCount: z.number(),
  pendingMessageCount: z.number(),
}) satisfies z.ZodType<PiSessionStatus>;

export const piSessionBashOutput = z.object({
  output: z.string(),
  exitCode: z.number().optional(),
  cancelled: z.boolean(),
  truncated: z.boolean(),
  fullOutputPath: z.string().optional(),
});

export const piSessionExportOutput = z.object({ path: z.string() });

export const piSessionForkOutput = z.object({
  text: z.string(),
  cancelled: z.boolean(),
});

export const piSessionForkMessagesOutput = z.array(
  z.object({ entryId: z.string(), text: z.string() }),
);

export const piSessionCommandsOutput = z.array(
  z.object({
    name: z.string(),
    description: z.string().optional(),
    source: z.enum(["extension", "prompt", "skill"]),
    sourceInfo: z.object({
      path: z.string(),
      source: z.string(),
      scope: z.enum(["user", "project", "temporary"]),
      origin: z.enum(["package", "top-level"]),
      baseDir: z.string().optional(),
    }),
  }),
) satisfies z.ZodType<PiCommand[]>;

export const piSessionLastAssistantTextOutput = z.string().nullable();
export const piSessionStderrOutput = z.string();
export const piSessionUnknownOutput = z.unknown();

export const resumePiSessionInput = z.object({
  taskId: z.string(),
  cwd: z.string(),
});

export const piSessionTranscriptInput = z.object({ taskId: z.string() });

export const piSessionPromptInput = piSessionTranscriptInput.extend({
  prompt: z.string().min(1),
  images: z.array(piImageContent).optional(),
});

export const piSessionMessageInput = piSessionTranscriptInput.extend({
  message: z.string().min(1),
  images: z.array(piImageContent).optional(),
});

export const piSessionBashInput = piSessionTranscriptInput.extend({
  command: z.string().min(1),
});

export const piSessionModelInput = piSessionTranscriptInput.extend({
  provider: z.string().min(1),
  modelId: z.string().min(1),
});

export const piSessionThinkingLevelInput = piSessionTranscriptInput.extend({
  level: piThinkingLevel,
});

export const piSessionQueueModeInput = piSessionTranscriptInput.extend({
  mode: piQueueMode,
});

export const piSessionCompactInput = piSessionTranscriptInput.extend({
  customInstructions: z.string().optional(),
});

export const piSessionEnabledInput = piSessionTranscriptInput.extend({
  enabled: z.boolean(),
});

export const piSessionNewInput = piSessionTranscriptInput.extend({
  parentSession: z.string().optional(),
});

export const piSessionPathInput = piSessionTranscriptInput.extend({
  sessionPath: z.string().min(1),
});

export const piSessionEntryInput = piSessionTranscriptInput.extend({
  entryId: z.string().min(1),
});

export const piSessionNameInput = piSessionTranscriptInput.extend({
  name: z.string().min(1),
});

export const piSessionExportInput = piSessionTranscriptInput.extend({
  outputPath: z.string().optional(),
});

export const piSessionTimeoutInput = piSessionTranscriptInput.extend({
  timeout: z.number().int().positive().optional(),
});

export const piSessionPromptAndWaitInput = piSessionPromptInput.extend({
  timeout: z.number().int().positive().optional(),
});

export const piSessionEntriesInput = piSessionTranscriptInput.extend({
  since: z.string().optional(),
});

export type StartPiSessionInput = z.infer<typeof startPiSessionInput>;
export type PiSessionPromptInput = z.infer<typeof piSessionPromptInput>;
