import {
  piRpcCommandSchema,
  piRpcResponseSchema,
} from "@posthog/agent/pi/rpc-transport";
import { z } from "zod";

export { piRpcResponseSchema };

export const startPiSessionInput = z.object({
  taskId: z.string(),
  cwd: z.string(),
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
});

export const piSessionTaskInput = z.object({ taskId: z.string() });

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
