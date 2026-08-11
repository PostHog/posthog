import { z } from "zod";

export const directoryEntrySchema = z.object({
  name: z.string(),
  path: z.string(),
  type: z.enum(["file", "directory"]),
});

export type DirectoryEntry = z.infer<typeof directoryEntrySchema>;

export const listDirectoryInput = z.object({ dirPath: z.string().min(1) });
export const listDirectoryOutput = z.array(directoryEntrySchema);

export const listRepoFilesInput = z.object({
  repoPath: z.string(),
  query: z.string().optional(),
  limit: z.number().optional(),
});

export const readRepoFileInput = z.object({
  repoPath: z.string(),
  filePath: z.string(),
});

export const readRepoFilesInput = z.object({
  repoPath: z.string(),
  filePaths: z.array(z.string()),
});

export const readRepoFileBoundedInput = z.object({
  repoPath: z.string(),
  filePath: z.string(),
  maxLines: z.number().int().positive(),
});

export const readRepoFilesBoundedInput = z.object({
  repoPath: z.string(),
  filePaths: z.array(z.string()),
  maxLines: z.number().int().positive(),
});

export const boundedReadResult = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("content"), content: z.string() }),
  z.object({ kind: z.literal("missing") }),
  z.object({ kind: z.literal("too-large") }),
]);

export const readRepoFilesBoundedOutput = z.record(
  z.string(),
  boundedReadResult,
);

export const readAbsoluteFileInput = z.object({
  filePath: z.string(),
});

export const writeRepoFileInput = z.object({
  repoPath: z.string(),
  filePath: z.string(),
  content: z.string(),
});

export const fileEntryKind = z.enum(["file", "directory"]);

const fileEntry = z.object({
  path: z.string(),
  name: z.string(),
  kind: fileEntryKind.default("file"),
  changed: z.boolean().optional(),
});

export const listRepoFilesOutput = z.array(fileEntry);
export const readRepoFileOutput = z.string().nullable();
export const readRepoFilesOutput = z.record(z.string(), readRepoFileOutput);

export type ListRepoFilesInput = z.infer<typeof listRepoFilesInput>;
export type ReadRepoFileInput = z.infer<typeof readRepoFileInput>;
export type ReadRepoFilesInput = z.infer<typeof readRepoFilesInput>;
export type WriteRepoFileInput = z.infer<typeof writeRepoFileInput>;
export type FileEntry = z.infer<typeof fileEntry>;
export type FileEntryKind = z.infer<typeof fileEntryKind>;
export type BoundedReadResult = z.infer<typeof boundedReadResult>;
