import { z } from "zod";

export const suspensionReasonSchema = z.enum([
  "max_worktrees",
  "inactivity",
  "manual",
]);

export type SuspensionReason = z.infer<typeof suspensionReasonSchema>;

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

export const suspensionSettingsSchema = z.object({
  autoSuspendEnabled: z.boolean(),
  maxActiveWorktrees: z.number().min(1),
  autoSuspendAfterDays: z.number().min(1),
});

export type SuspensionSettings = z.infer<typeof suspensionSettingsSchema>;

export const suspendTaskInput = z.object({
  taskId: z.string(),
  reason: suspensionReasonSchema.optional().default("manual"),
});

export type SuspendTaskInput = z.infer<typeof suspendTaskInput>;

export const restoreTaskInput = z.object({
  taskId: z.string(),
  recreateBranch: z.boolean().optional(),
});

export type RestoreTaskInput = z.infer<typeof restoreTaskInput>;

export const suspendTaskOutput = suspendedTaskSchema;

export const restoreTaskOutput = z.object({
  taskId: z.string(),
  worktreeName: z.string().nullable(),
});

export const listSuspendedTasksOutput = z.array(suspendedTaskSchema);

export const suspendedTaskIdsOutput = z.array(z.string());

export const suspensionSettingsOutput = suspensionSettingsSchema;

export const updateSuspensionSettingsInput = suspensionSettingsSchema.partial();
