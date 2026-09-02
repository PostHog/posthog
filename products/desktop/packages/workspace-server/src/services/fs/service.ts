import fs from "node:fs/promises";
import path from "node:path";
import { getChangedFiles, listAllFiles } from "@posthog/git/queries";
import { injectable } from "inversify";
import type { BoundedReadResult, DirectoryEntry, FileEntry } from "./schemas";

@injectable()
export class FsService {
  private static readonly CACHE_TTL = 30000;
  private static readonly READ_REPO_FILES_CONCURRENCY = 24;
  private static readonly MAX_REPO_FILES = 50_000;
  private static readonly LIST_FILES_TIMEOUT_MS = 8_000;
  private cache = new Map<string, { files: FileEntry[]; timestamp: number }>();

  async listDirectory(dirPath: string): Promise<DirectoryEntry[]> {
    try {
      const entries = await fs.readdir(dirPath, { withFileTypes: true });
      return entries
        .filter((e) => !e.name.startsWith("."))
        .map((e) => ({
          name: e.name,
          path: path.join(dirPath, e.name),
          type: e.isDirectory() ? ("directory" as const) : ("file" as const),
        }))
        .sort((a, b) =>
          a.type !== b.type
            ? a.type === "directory"
              ? -1
              : 1
            : a.name.localeCompare(b.name),
        );
    } catch {
      return [];
    }
  }

  async listRepoFiles(
    repoPath: string,
    query?: string,
    limit?: number,
  ): Promise<FileEntry[]> {
    if (!repoPath) return [];

    try {
      const changedFiles = await getChangedFiles(repoPath);

      if (query?.trim()) {
        const allFiles = await this.listAllFilesBounded(repoPath);
        const directories = this.deriveDirectories(allFiles);
        const lowerQuery = query.toLowerCase();
        const matchingDirs = directories.filter((d) =>
          d.toLowerCase().includes(lowerQuery),
        );
        const matchingFiles = allFiles.filter((f) =>
          f.toLowerCase().includes(lowerQuery),
        );
        const entries = [
          ...this.toDirectoryEntries(matchingDirs),
          ...this.toFileEntries(matchingFiles, changedFiles),
        ];
        return limit ? entries.slice(0, limit) : entries;
      }

      const cached = this.cache.get(repoPath);
      if (cached && Date.now() - cached.timestamp < FsService.CACHE_TTL) {
        return limit ? cached.files.slice(0, limit) : cached.files;
      }

      const files = await this.listAllFilesBounded(repoPath);
      const directories = this.deriveDirectories(files);
      const entries = [
        ...this.toDirectoryEntries(directories),
        ...this.toFileEntries(files, changedFiles),
      ];
      this.cache.set(repoPath, { files: entries, timestamp: Date.now() });

      return limit ? entries.slice(0, limit) : entries;
    } catch {
      return [];
    }
  }

  invalidateCache(repoPath?: string): void {
    if (repoPath) {
      this.cache.delete(repoPath);
    } else {
      this.cache.clear();
    }
  }

  async readRepoFile(
    repoPath: string,
    filePath: string,
  ): Promise<string | null> {
    try {
      return await fs.readFile(this.resolvePath(repoPath, filePath), "utf-8");
    } catch {
      return null;
    }
  }

  async readRepoFiles(
    repoPath: string,
    filePaths: string[],
  ): Promise<Record<string, string | null>> {
    const uniqueFilePaths = [...new Set(filePaths)];
    const entries = await this.mapWithConcurrency(
      uniqueFilePaths,
      FsService.READ_REPO_FILES_CONCURRENCY,
      async (filePath) =>
        [filePath, await this.readRepoFile(repoPath, filePath)] as const,
    );
    return Object.fromEntries(entries);
  }

  async readRepoFileBounded(
    repoPath: string,
    filePath: string,
    maxLines: number,
  ): Promise<BoundedReadResult> {
    try {
      const content = await fs.readFile(
        this.resolvePath(repoPath, filePath),
        "utf-8",
      );
      if (exceedsLineLimit(content, maxLines)) {
        return { kind: "too-large" };
      }
      return { kind: "content", content };
    } catch {
      return { kind: "missing" };
    }
  }

  async readRepoFilesBounded(
    repoPath: string,
    filePaths: string[],
    maxLines: number,
  ): Promise<Record<string, BoundedReadResult>> {
    const uniqueFilePaths = [...new Set(filePaths)];
    const entries = await this.mapWithConcurrency(
      uniqueFilePaths,
      FsService.READ_REPO_FILES_CONCURRENCY,
      async (filePath) =>
        [
          filePath,
          await this.readRepoFileBounded(repoPath, filePath, maxLines),
        ] as const,
    );
    return Object.fromEntries(entries);
  }

  async readAbsoluteFile(filePath: string): Promise<string | null> {
    try {
      return await fs.readFile(path.resolve(filePath), "utf-8");
    } catch {
      return null;
    }
  }

  async readFileAsBase64(filePath: string): Promise<string | null> {
    const resolved = path.resolve(filePath);
    try {
      const buffer = await fs.readFile(resolved);
      return buffer.toString("base64");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        return null;
      }
      const dir = path.dirname(resolved);
      const basename = path.basename(resolved);
      try {
        const files = await fs.readdir(dir);
        const normalizeSpaces = (s: string) => s.replace(/[\s  ]/g, " ");
        const normalizedTarget = normalizeSpaces(basename);
        const match = files.find(
          (f) => normalizeSpaces(f) === normalizedTarget,
        );
        if (match) {
          const buffer = await fs.readFile(path.join(dir, match));
          return buffer.toString("base64");
        }
      } catch {}
      return null;
    }
  }

  async writeRepoFile(
    repoPath: string,
    filePath: string,
    content: string,
  ): Promise<void> {
    await fs.writeFile(this.resolvePath(repoPath, filePath), content, "utf-8");
    this.invalidateCache(repoPath);
  }

  private resolvePath(repoPath: string, filePath: string): string {
    const base = path.resolve(repoPath);
    const resolved = path.resolve(base, filePath);
    if (resolved !== base && !resolved.startsWith(base + path.sep)) {
      throw new Error("Access denied: path outside repository");
    }
    return resolved;
  }

  private toFileEntries(
    files: string[],
    changedFiles: Set<string>,
  ): FileEntry[] {
    return files.map((p) => ({
      path: p,
      name: path.basename(p),
      kind: "file",
      changed: changedFiles.has(p),
    }));
  }

  private toDirectoryEntries(directories: string[]): FileEntry[] {
    return directories.map((p) => ({
      path: p,
      name: path.basename(p),
      kind: "directory",
    }));
  }

  private listAllFilesBounded(repoPath: string): Promise<string[]> {
    return listAllFiles(repoPath, {
      maxFiles: FsService.MAX_REPO_FILES,
      timeoutMs: FsService.LIST_FILES_TIMEOUT_MS,
    });
  }

  private deriveDirectories(files: string[]): string[] {
    const dirs = new Set<string>();
    for (const file of files) {
      let parent = path.posix.dirname(file);
      while (parent && parent !== "." && parent !== "/") {
        if (dirs.has(parent)) break;
        dirs.add(parent);
        parent = path.posix.dirname(parent);
      }
    }
    return Array.from(dirs).sort();
  }

  private async mapWithConcurrency<T, R>(
    items: readonly T[],
    concurrency: number,
    mapper: (item: T) => Promise<R>,
  ): Promise<R[]> {
    if (items.length === 0) return [];

    const results = new Array<R>(items.length);
    let index = 0;

    const worker = async () => {
      while (index < items.length) {
        const currentIndex = index++;
        results[currentIndex] = await mapper(items[currentIndex]);
      }
    };

    await Promise.all(
      Array.from({ length: Math.min(concurrency, items.length) }, () =>
        worker(),
      ),
    );

    return results;
  }
}

function exceedsLineLimit(content: string, maxLines: number): boolean {
  let lineCount = 1;
  for (let i = 0; i < content.length; i++) {
    if (content.charCodeAt(i) === 10) {
      lineCount++;
      if (lineCount > maxLines) {
        return true;
      }
    }
  }
  return false;
}
