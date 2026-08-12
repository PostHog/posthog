import type { BoundedReadResult, FileEntry } from "./schemas";

export const FS_SERVICE = Symbol.for("posthog.workspace.fsService");

export interface FsCapability {
  listRepoFiles(
    repoPath: string,
    query?: string,
    limit?: number,
  ): Promise<FileEntry[]>;
  readRepoFile(repoPath: string, filePath: string): Promise<string | null>;
  readRepoFiles(
    repoPath: string,
    filePaths: string[],
  ): Promise<Record<string, string | null>>;
  readRepoFileBounded(
    repoPath: string,
    filePath: string,
    maxLines: number,
  ): Promise<BoundedReadResult>;
  readRepoFilesBounded(
    repoPath: string,
    filePaths: string[],
    maxLines: number,
  ): Promise<Record<string, BoundedReadResult>>;
  readAbsoluteFile(filePath: string): Promise<string | null>;
  readFileAsBase64(filePath: string): Promise<string | null>;
  writeRepoFile(
    repoPath: string,
    filePath: string,
    content: string,
  ): Promise<void>;
}
