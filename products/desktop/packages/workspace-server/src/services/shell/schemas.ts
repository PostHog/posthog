import { z } from "zod";

export const sessionIdInput = z.object({
  sessionId: z.string(),
});

export const createInput = sessionIdInput.extend({
  cwd: z.string().optional(),
  taskId: z.string().optional(),
});

export const createCommandInput = sessionIdInput.extend({
  command: z.string().min(1),
  cwd: z.string(),
  taskId: z.string().optional(),
});

export const writeInput = sessionIdInput.extend({
  data: z.string(),
});

export const resizeInput = sessionIdInput.extend({
  cols: z.number(),
  rows: z.number(),
});

export const executeInput = z.object({
  cwd: z.string(),
  command: z.string(),
});

export const executeOutput = z.object({
  stdout: z.string(),
  stderr: z.string(),
  exitCode: z.number(),
});

export type SessionIdInput = z.infer<typeof sessionIdInput>;
export type CreateInput = z.infer<typeof createInput>;
export type CreateCommandInput = z.infer<typeof createCommandInput>;
export type WriteInput = z.infer<typeof writeInput>;
export type ResizeInput = z.infer<typeof resizeInput>;
export type ExecuteInput = z.infer<typeof executeInput>;
export type ExecuteOutput = z.infer<typeof executeOutput>;

export const ShellEvent = {
  Data: "data",
  Exit: "exit",
} as const;

export type ShellDataPayload = {
  sessionId: string;
  data: string;
};

export type ShellExitPayload = {
  sessionId: string;
  exitCode: number;
};

export interface ShellEvents {
  [ShellEvent.Data]: ShellDataPayload;
  [ShellEvent.Exit]: ShellExitPayload;
}
