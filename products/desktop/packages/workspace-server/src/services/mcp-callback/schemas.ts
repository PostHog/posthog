import { z } from "zod";

export const mcpCallbackResult = z.object({
  status: z.enum(["success", "error"]),
  installationId: z.string().optional(),
  error: z.string().optional(),
});
export type McpCallbackResult = z.infer<typeof mcpCallbackResult>;

export const getCallbackUrlOutput = z.object({
  callbackUrl: z.string(),
});
export type GetCallbackUrlOutput = z.infer<typeof getCallbackUrlOutput>;

export const openAndWaitInput = z.object({
  redirectUrl: z.string(),
});
export type OpenAndWaitInput = z.infer<typeof openAndWaitInput>;

export const openAndWaitOutput = z.object({
  success: z.boolean(),
  installationId: z.string().optional(),
  error: z.string().optional(),
});
export type OpenAndWaitOutput = z.infer<typeof openAndWaitOutput>;

export enum McpCallbackEvent {
  OAuthComplete = "mcpOAuthComplete",
}

export interface McpCallbackEvents {
  [McpCallbackEvent.OAuthComplete]: McpCallbackResult;
}
