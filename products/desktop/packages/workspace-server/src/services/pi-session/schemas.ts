import {
  piRpcCommandSchema,
  piRpcResponseSchema,
} from "@posthog/agent/pi/rpc-transport";
import {
  PI_THINKING_LEVELS,
  piExtensionEventSchema,
  type RpcExtensionUIResponse,
} from "@posthog/agent/pi/types";
import { z } from "zod";

export { piExtensionEventSchema, piRpcResponseSchema };

const piTaskContextInput = z.object({
  taskId: z.string(),
  cwd: z.string(),
  customInstructions: z.string().optional(),
  additionalDirectories: z.array(z.string()).optional(),
  channelMode: z.boolean().optional(),
});

export const startPiSessionInput = z.object({
  taskContext: piTaskContextInput,
  prompt: z.string(),
  model: z.string().optional(),
  thinkingLevel: z.enum(PI_THINKING_LEVELS).optional(),
  /**
   * When set, and the user is actually logged in, run this session on the
   * user's own Anthropic/OpenAI Codex subscription instead of PostHog's
   * gateway. Overrides `model` with that provider's default.
   */
  piSubscriptionProvider: z.enum(["anthropic", "openai-codex"]).optional(),
});

export type StartPiSessionInput = z.infer<typeof startPiSessionInput>;

export const piSessionStartOutput = z.object({
  sessionFile: z.string().nullable(),
  sessionId: z.string(),
});

export const piSessionHealthOutput = z.object({
  state: z.enum(["cold", "starting", "idle", "streaming"]),
  pid: z.number().optional(),
  lastUsedAt: z.number().optional(),
});

export const resumePiSessionInput = z.object({
  taskContext: piTaskContextInput.pick({ taskId: true, cwd: true }),
});

export type ResumePiSessionInput = z.infer<typeof resumePiSessionInput>;

export const piSessionTaskInput = z.object({ taskId: z.string() });

const mcpToolPermissionRequestSchema = z.object({
  requestId: z.string(),
  serverName: z.string(),
  toolName: z.string(),
  installationId: z.string(),
  arguments: z.record(z.string(), z.unknown()),
  description: z.string().optional(),
});

export const respondMcpToolPermissionInput = z.object({
  taskId: z.string(),
  request: mcpToolPermissionRequestSchema,
  decision: z.enum(["allow", "allow_always", "reject"]),
});

export const piSessionConfigInput = z.object({ downloadUrl: z.url() });

export const piSessionConfigOutput = z
  .object({
    model: z
      .object({
        provider: z.string(),
        id: z.string(),
      })
      .nullable(),
    thinkingLevel: z.enum(PI_THINKING_LEVELS),
  })
  .nullable();

export const piQueueSnapshotOutput = z.object({
  steering: z.array(z.string()),
  followUp: z.array(z.string()),
});

export const piSessionRpcInput = z.object({
  taskId: z.string(),
  command: piRpcCommandSchema,
});

type IsEqual<Left, Right> = [Left] extends [Right]
  ? [Right] extends [Left]
    ? true
    : false
  : false;

type OptionalKeys<Value> = {
  [Key in keyof Value]-?: Record<never, never> extends Pick<Value, Key>
    ? Key
    : never;
}[keyof Value];

type IsExactObject<Actual, Expected> = IsEqual<Actual, Expected> extends true
  ? IsEqual<keyof Actual, keyof Expected> extends true
    ? IsEqual<OptionalKeys<Actual>, OptionalKeys<Expected>>
    : false
  : false;

function exactObjectOutputSchema<Expected>() {
  return <Schema extends z.ZodType>(
    schema: Schema &
      (IsExactObject<z.output<Schema>, Expected> extends true
        ? unknown
        : never),
  ): Schema => schema;
}

const piExtensionValueResponseSchema = exactObjectOutputSchema<
  Extract<RpcExtensionUIResponse, { value: string }>
>()(
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    value: z.string(),
  }),
);

const piExtensionConfirmationResponseSchema = exactObjectOutputSchema<
  Extract<RpcExtensionUIResponse, { confirmed: boolean }>
>()(
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    confirmed: z.boolean(),
  }),
);

const piExtensionCancellationResponseSchema = exactObjectOutputSchema<
  Extract<RpcExtensionUIResponse, { cancelled: true }>
>()(
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    cancelled: z.literal(true),
  }),
);

const piExtensionUIResponseSchema = z.union([
  piExtensionValueResponseSchema,
  piExtensionConfirmationResponseSchema,
  piExtensionCancellationResponseSchema,
]);

export const piExtensionUIResponseInput = z.object({
  taskId: z.string(),
  response: piExtensionUIResponseSchema,
});
