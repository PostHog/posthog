import {
  piRpcCommandSchema,
  piRpcResponseSchema,
} from "@posthog/agent/pi/rpc-transport";
import {
  PI_THINKING_LEVELS,
  type PiExtensionError,
  type RpcExtensionUIRequest,
  type RpcExtensionUIResponse,
} from "@posthog/agent/pi/types";
import { z } from "zod";

export { piRpcResponseSchema };

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

export const mcpToolPermissionRequestSchema = z.object({
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

type WithOptionalProperty<T, Key extends keyof T> = Omit<T, Key> &
  Partial<Pick<T, Key>>;

type PiExtensionUIWireRequest =
  | Exclude<RpcExtensionUIRequest, { method: "setStatus" | "setWidget" }>
  | WithOptionalProperty<
      Extract<RpcExtensionUIRequest, { method: "setStatus" }>,
      "statusText"
    >
  | WithOptionalProperty<
      Extract<RpcExtensionUIRequest, { method: "setWidget" }>,
      "widgetLines"
    >;

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

type DiscriminantValues<
  Union,
  Discriminant extends PropertyKey,
> = Union extends Record<Discriminant, infer Value extends PropertyKey>
  ? Value
  : never;

type ExactMemberChecks<Actual, Expected, Discriminant extends PropertyKey> = {
  [Value in DiscriminantValues<Expected, Discriminant>]: IsExactObject<
    Extract<Actual, Record<Discriminant, Value>>,
    Extract<Expected, Record<Discriminant, Value>>
  >;
}[DiscriminantValues<Expected, Discriminant>];

type IsExactDiscriminatedUnion<
  Actual,
  Expected,
  Discriminant extends PropertyKey,
> = IsEqual<
  DiscriminantValues<Actual, Discriminant>,
  DiscriminantValues<Expected, Discriminant>
> extends true
  ? [ExactMemberChecks<Actual, Expected, Discriminant>] extends [true]
    ? true
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

function exactDiscriminatedOutputSchema<
  Expected,
  Discriminant extends PropertyKey,
>() {
  return <Schema extends z.ZodType>(
    schema: Schema &
      (IsExactDiscriminatedUnion<
        z.output<Schema>,
        Expected,
        Discriminant
      > extends true
        ? unknown
        : never),
  ): Schema => schema;
}

const extensionRequestBase = {
  type: z.literal("extension_ui_request"),
  id: z.string(),
};

const piExtensionUIWireRequestSchema = exactDiscriminatedOutputSchema<
  PiExtensionUIWireRequest,
  "method"
>()(
  z.discriminatedUnion("method", [
    z.object({
      ...extensionRequestBase,
      method: z.literal("select"),
      title: z.string(),
      options: z.array(z.string()),
      timeout: z.number().optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("confirm"),
      title: z.string(),
      message: z.string(),
      timeout: z.number().optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("input"),
      title: z.string(),
      placeholder: z.string().optional(),
      timeout: z.number().optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("editor"),
      title: z.string(),
      prefill: z.string().optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("notify"),
      message: z.string(),
      notifyType: z.enum(["info", "warning", "error"]).optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("setStatus"),
      statusKey: z.string(),
      statusText: z.string().optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("setWidget"),
      widgetKey: z.string(),
      widgetLines: z.array(z.string()).optional(),
      widgetPlacement: z.enum(["aboveEditor", "belowEditor"]).optional(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("setTitle"),
      title: z.string(),
    }),
    z.object({
      ...extensionRequestBase,
      method: z.literal("set_editor_text"),
      text: z.string(),
    }),
  ]),
);

export const piExtensionUIRequestSchema =
  piExtensionUIWireRequestSchema.transform((request): RpcExtensionUIRequest => {
    if (request.method === "setStatus") {
      return { ...request, statusText: request.statusText };
    }
    if (request.method === "setWidget") {
      return { ...request, widgetLines: request.widgetLines };
    }
    return request;
  });

export const piExtensionErrorSchema =
  exactObjectOutputSchema<PiExtensionError>()(
    z.object({
      type: z.literal("extension_error"),
      extensionPath: z.string(),
      event: z.string(),
      error: z.string(),
      stack: z.string().optional(),
    }),
  );

export const piExtensionEventSchema = z.union([
  piExtensionUIRequestSchema,
  piExtensionErrorSchema,
]);

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

export const piExtensionUIResponseSchema = z.union([
  piExtensionValueResponseSchema,
  piExtensionConfirmationResponseSchema,
  piExtensionCancellationResponseSchema,
]);

export const piExtensionUIResponseInput = z.object({
  taskId: z.string(),
  response: piExtensionUIResponseSchema,
});
