import { z } from "zod";

export const fetchS3LogsInput = z.object({ logUrl: z.string().min(1) });
export const fetchS3LogsOutput = z.string().nullable();

export const readLocalLogsInput = z.object({ taskRunId: z.string().min(1) });
export const readLocalLogsOutput = z.string().nullable();

export const readLocalLogsCollapsedInput = z.object({
  taskRunId: z.string().min(1),
});
export const readLocalLogsCollapsedOutput = z
  .object({
    content: z.string(),
    totalLineCount: z.number().int().nonnegative(),
  })
  .nullable();

export const readLocalLogsTailInput = z.object({
  taskRunId: z.string().min(1),
  maxBytes: z.number().int().positive(),
});
export const readLocalLogsTailOutput = z
  .object({ content: z.string(), truncated: z.boolean() })
  .nullable();

export const writeLocalLogsInput = z.object({
  taskRunId: z.string().min(1),
  content: z.string(),
});

export const seedLocalLogsInput = z.object({
  taskRunId: z.string().min(1),
  content: z.string(),
});

export const countLocalLogEntriesInput = z.object({
  taskRunId: z.string().min(1),
});
export const countLocalLogEntriesOutput = z.number();

export const deleteLocalLogCacheInput = z.object({
  taskRunId: z.string().min(1),
});
