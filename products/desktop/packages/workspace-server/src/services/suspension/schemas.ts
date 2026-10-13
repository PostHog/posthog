import { z } from "zod";

const suspensionReasonSchema = z.enum([
  "max_worktrees",
  "inactivity",
  "manual",
]);

export const suspendedTaskSchema = z.object({
  taskId: z.string(),
  suspendedAt: z.string(),
  reason: suspensionReasonSchema,
  folderId: z.string(),
  mode: z.enum(["worktree", "local", "cloud"]),
  worktreeName: z.string().nullable(),
  branchName: z.string().nullable(),
  checkpointId: z.string().nullable(),
});

export type SuspendedTask = z.infer<typeof suspendedTaskSchema>;

const suspensionSettingsSchema = z.object({
  autoSuspendEnabled: z.boolean(),
  maxActiveWorktrees: z.number().min(1),
  autoSuspendAfterDays: z.number().min(1),
});

export const suspendTaskInput = z.object({
  taskId: z.string(),
  reason: suspensionReasonSchema.optional().default("manual"),
});

export const restoreTaskInput = z.object({
  taskId: z.string(),
  recreateBranch: z.boolean().optional(),
});

export const suspendTaskOutput = suspendedTaskSchema;

export const restoreTaskOutput = z.object({
  taskId: z.string(),
  worktreeName: z.string().nullable(),
});

export const listSuspendedTasksOutput = z.array(suspendedTaskSchema);

export const suspendedTaskIdsOutput = z.array(z.string());

export const suspensionSettingsOutput = suspensionSettingsSchema;

export const updateSuspensionSettingsInput = suspensionSettingsSchema.partial();
