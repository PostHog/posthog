import { z } from "zod";
import type { McpRelayExecution } from "./identifiers";

export const executeMcpRelayInput = z.object({
  runId: z.string(),
  server: z.string(),
  payload: z.record(z.string(), z.unknown()),
});

export const executeMcpRelayOutput: z.ZodType<McpRelayExecution> = z.object({
  payload: z.record(z.string(), z.unknown()).optional(),
  error: z.object({ code: z.number(), message: z.string() }).optional(),
});

export const closeRunInput = z.object({
  runId: z.string(),
});
