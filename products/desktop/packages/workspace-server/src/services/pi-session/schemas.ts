import {
  piRpcCommandSchema,
  piRpcResponseSchema,
} from "@posthog/agent/pi/rpc-transport";
import { z } from "zod";

export { piRpcResponseSchema };

export const startPiSessionInput = z.object({
  taskId: z.string(),
  cwd: z.string(),
  projectTrustPath: z.string().optional(),
  prompt: z.string(),
  model: z.string().optional(),
  thinkingLevel: z
    .enum(["off", "minimal", "low", "medium", "high", "xhigh", "max"])
    .optional(),
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
  taskId: z.string(),
  cwd: z.string(),
  projectTrustPath: z.string().optional(),
});

export const piSessionTaskInput = z.object({ taskId: z.string() });

export const piProjectTrustOutput = z.object({
  trusted: z.boolean(),
  hasProjectResources: z.boolean(),
});

export const setPiProjectTrustInput = z.object({
  taskId: z.string(),
  trusted: z.boolean(),
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
    thinkingLevel: z.enum([
      "off",
      "minimal",
      "low",
      "medium",
      "high",
      "xhigh",
      "max",
    ]),
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

const extensionRequestBase = {
  type: z.literal("extension_ui_request"),
  id: z.string(),
};

export const piExtensionUIRequestSchema = z.discriminatedUnion("method", [
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
]);

export const piExtensionErrorSchema = z.object({
  type: z.literal("extension_error"),
  extensionPath: z.string(),
  event: z.string(),
  error: z.string(),
});

export const piExtensionSessionResetSchema = z.object({
  type: z.literal("extension_session_reset"),
});

export const piExtensionDialogExpiredSchema = z.object({
  type: z.literal("extension_dialog_expired"),
  id: z.string(),
});

export const piExtensionStateSnapshotSchema = z.object({
  type: z.literal("extension_state_snapshot"),
  dialogs: z.array(
    z.union([
      piExtensionUIRequestSchema.options[0],
      piExtensionUIRequestSchema.options[1],
      piExtensionUIRequestSchema.options[2],
      piExtensionUIRequestSchema.options[3],
    ]),
  ),
  statuses: z.array(piExtensionUIRequestSchema.options[5]),
  widgets: z.array(piExtensionUIRequestSchema.options[6]),
  title: piExtensionUIRequestSchema.options[7].optional(),
  editorText: piExtensionUIRequestSchema.options[8].optional(),
});

export const piExtensionEventSchema = z.union([
  piExtensionUIRequestSchema,
  piExtensionErrorSchema,
  piExtensionSessionResetSchema,
  piExtensionDialogExpiredSchema,
  piExtensionStateSnapshotSchema,
]);

export const piExtensionUIResponseSchema = z.union([
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    value: z.string(),
  }),
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    confirmed: z.boolean(),
  }),
  z.object({
    type: z.literal("extension_ui_response"),
    id: z.string(),
    cancelled: z.literal(true),
  }),
]);

export const piExtensionUIResponseInput = z.object({
  taskId: z.string(),
  response: piExtensionUIResponseSchema,
});

export const piExtensionEditorTextAckInput = z.object({
  taskId: z.string(),
  id: z.string(),
});
