import { z } from "zod";

export const processCategorySchema = z.enum(["shell", "agent", "child"]);
export type ProcessCategory = z.infer<typeof processCategorySchema>;

export const trackedProcessSchema = z.object({
  pid: z.number(),
  category: processCategorySchema,
  label: z.string(),
  registeredAt: z.number(),
  taskId: z.string().optional(),
  metadata: z.record(z.string(), z.string()).optional(),
});
export type TrackedProcess = z.infer<typeof trackedProcessSchema>;

export const discoveredProcessSchema = z.object({
  pid: z.number(),
  ppid: z.number(),
  command: z.string(),
  tracked: z.boolean(),
});
export type DiscoveredProcess = z.infer<typeof discoveredProcessSchema>;

export const processSnapshotSchema = z.object({
  tracked: z.object({
    shell: z.array(trackedProcessSchema),
    agent: z.array(trackedProcessSchema),
    child: z.array(trackedProcessSchema),
  }),
  discovered: z.array(discoveredProcessSchema).optional(),
  timestamp: z.number(),
});
export type ProcessSnapshot = z.infer<typeof processSnapshotSchema>;

export const getSnapshotInput = z
  .object({
    includeDiscovered: z.boolean().optional(),
  })
  .optional();

export const killByPidInput = z.object({ pid: z.number() });
export const killByCategoryInput = z.object({
  category: processCategorySchema,
});
export const killByTaskIdInput = z.object({ taskId: z.string() });
export const listByTaskIdInput = z.object({ taskId: z.string() });
