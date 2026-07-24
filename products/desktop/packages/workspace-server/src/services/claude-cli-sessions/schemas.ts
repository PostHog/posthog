import { z } from "zod";

export const cliSessionFingerprintSchema = z.object({
  sourceMtimeMs: z.number(),
  sourceSizeBytes: z.number(),
  sourceLastEntryUuid: z.string().nullable(),
});

export const listCliSessionsInput = z.object({
  repoPath: z.string(),
});

export const cliSessionSummarySchema = z.object({
  sourceSessionId: z.string(),
  cwd: z.string(),
  title: z.string().nullable(),
  lastPrompt: z.string().nullable(),
  /** ISO timestamp from the source file's mtime. */
  updatedAt: z.string(),
  sizeBytes: z.number(),
  gitBranch: z.string().nullable(),
  /**
   * new: never imported. imported: snapshot matches the source.
   * updated: the CLI session changed after the last import.
   */
  status: z.enum(["new", "imported", "updated"]),
  importedTaskId: z.string().nullable(),
});

export const listCliSessionsOutput = z.object({
  sessions: z.array(cliSessionSummarySchema),
});

export const importCliSessionInput = z.object({
  repoPath: z.string(),
  /** uuid keeps the value safe to use as a path segment. */
  sourceSessionId: z.string().uuid(),
});

export const importCliSessionOutput = z.object({
  importedSessionId: z.string(),
  fingerprint: cliSessionFingerprintSchema,
});

export const deleteImportedCliSessionInput = z.object({
  repoPath: z.string(),
  /** uuid keeps the value safe to use as a path segment. */
  importedSessionId: z.string().uuid(),
});

export const deleteImportRecordInput = z.object({
  /** uuid keeps the value safe to use as a path segment. */
  importedSessionId: z.string().uuid(),
});

export const recordCliImportInput = z.object({
  sourceSessionId: z.string().uuid(),
  /** uuid keeps the value safe to use as a path segment. */
  importedSessionId: z.string().uuid(),
  repoPath: z.string(),
  taskId: z.string(),
  fingerprint: cliSessionFingerprintSchema,
});

export type CliSessionFingerprint = z.infer<typeof cliSessionFingerprintSchema>;
export type CliSessionSummary = z.infer<typeof cliSessionSummarySchema>;
export type ListCliSessionsInput = z.infer<typeof listCliSessionsInput>;
export type ListCliSessionsOutput = z.infer<typeof listCliSessionsOutput>;
export type ImportCliSessionInput = z.infer<typeof importCliSessionInput>;
export type ImportCliSessionOutput = z.infer<typeof importCliSessionOutput>;
export type DeleteImportedCliSessionInput = z.infer<
  typeof deleteImportedCliSessionInput
>;
export type DeleteImportRecordInput = z.infer<typeof deleteImportRecordInput>;
export type RecordCliImportInput = z.infer<typeof recordCliImportInput>;
