import { z } from "zod";

export const watcherEventSchema = z.object({
  type: z.enum(["create", "update", "delete"]),
  path: z.string(),
});

export type WatcherEvent = z.infer<typeof watcherEventSchema>;

export const watchInput = z.object({
  dirPath: z.string().min(1),
  ignore: z.array(z.string()).optional(),
});

export const resolveGitDirsInput = z.object({ repoPath: z.string().min(1) });
export const resolveGitDirsOutput = z.object({
  gitDir: z.string().nullable(),
  commonDir: z.string().nullable(),
});

export const fileWatcherEventSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("directory-changed"),
    repoPath: z.string(),
    dirPath: z.string(),
  }),
  z.object({
    kind: z.literal("file-changed"),
    repoPath: z.string(),
    filePath: z.string(),
  }),
  z.object({
    kind: z.literal("file-deleted"),
    repoPath: z.string(),
    filePath: z.string(),
  }),
  z.object({
    kind: z.literal("git-state-changed"),
    repoPath: z.string(),
  }),
  z.object({
    kind: z.literal("working-tree-changed"),
    repoPath: z.string(),
  }),
]);

export type FileWatcherEvent = z.infer<typeof fileWatcherEventSchema>;
export type FileWatcherEventKind = FileWatcherEvent["kind"];

export const FileWatcherEventKind = {
  DirectoryChanged: "directory-changed",
  FileChanged: "file-changed",
  FileDeleted: "file-deleted",
  GitStateChanged: "git-state-changed",
  WorkingTreeChanged: "working-tree-changed",
} as const;

export const watchRepoInput = z.object({ repoPath: z.string().min(1) });
