import fs from "node:fs/promises";
import path from "node:path";
import { getChangedFiles, listAllFiles } from "@posthog/git/queries";
import { injectable } from "inversify";
import type { BoundedReadResult, DirectoryEntry, FileEntry } from "./schemas";

// Matches Linux's own MAXSYMLINKS, so any chain we refuse the OS would too.
const MAX_SYMLINK_HOPS = 40;

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
      return await fs.readFile(
        await this.resolvePath(repoPath, filePath),
        "utf-8",
      );
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
        await this.resolvePath(repoPath, filePath),
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

  // Read an in-repo binary (image/video preview) as base64, confined to the repo
  // so a symlink committed under a binary filename cannot escape it. This is the
  // only base64 read path for repo files; readFileAsBase64 below is reserved for
  // genuine out-of-repo, user-chosen files (e.g. attachment upload).
  async readRepoFileAsBase64(
    repoPath: string,
    filePath: string,
  ): Promise<string | null> {
    try {
      const buffer = await fs.readFile(
        await this.resolvePath(repoPath, filePath),
      );
      return buffer.toString("base64");
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
    await fs.writeFile(
      await this.resolvePath(repoPath, filePath),
      content,
      "utf-8",
    );
    this.invalidateCache(repoPath);
  }

  private async resolvePath(
    repoPath: string,
    filePath: string,
  ): Promise<string> {
    const base = path.resolve(repoPath);
    const resolved = path.resolve(base, filePath);
    // Lexical containment rejects `../` escapes.
    if (resolved !== base && !resolved.startsWith(base + path.sep)) {
      throw new Error("Access denied: path outside repository");
    }
    // Symlink-aware containment: a symlink committed inside the repo can point
    // outside it, which the lexical check above cannot see. Resolve the real
    // target the OS would open and confirm it is still inside the repo's real
    // base.
    const realBase = await fs.realpath(base);
    if (resolved === base) {
      return resolved;
    }
    const realTarget = await realTargetForContainment(resolved);
    if (
      realTarget !== realBase &&
      !realTarget.startsWith(realBase + path.sep)
    ) {
      throw new Error("Access denied: path escapes repository via symlink");
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

// Resolve the real path the OS would open for `resolved`, resolving each parent
// directory with realpath but inspecting the final component with lstat.
// realpath alone cannot tell a not-yet-created file apart from a *dangling*
// symlink -- one whose own name exists but whose target does not -- because it
// throws ENOENT for both. A dangling symlink pointing outside the repo would
// then be mistaken for an in-repo new file, and fs.writeFile would follow it and
// create a file outside the repo. Resolving the parent and lstat-ing the leaf
// closes that gap while still allowing legitimate new-file writes.
//
// The walk repeats per link because only the terminal target is read or written,
// and a single hop is not enough to find it: with `a -> b` in the repo and a
// dangling `b -> /outside/missing`, resolving `a` one hop lands on the in-repo
// name `b`, which realpath cannot resolve past (the chain dangles) and which
// therefore reads as contained while the OS still follows both links out.
async function realTargetForContainment(resolved: string): Promise<string> {
  let current = resolved;
  for (let hop = 0; hop <= MAX_SYMLINK_HOPS; hop++) {
    const realParent = await realpathAllowingMissing(path.dirname(current));
    const leaf = path.join(realParent, path.basename(current));
    let stats: Awaited<ReturnType<typeof fs.lstat>>;
    try {
      stats = await fs.lstat(leaf);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
      return leaf;
    }
    if (!stats.isSymbolicLink()) {
      return leaf;
    }
    current = path.resolve(realParent, await fs.readlink(leaf));
  }
  // Only reachable via a symlink cycle or an absurdly long chain, which the OS
  // would refuse with ELOOP anyway. Fail closed rather than return a guess.
  throw new Error("Access denied: symlink chain too deep");
}

// Resolve symlinks on the deepest existing prefix of `target`, then re-append
// any not-yet-existing tail (which cannot contain symlinks precisely because it
// does not exist). Lets containment see through a symlink while still allowing
// writes that create new files or directories.
async function realpathAllowingMissing(target: string): Promise<string> {
  const { root } = path.parse(target);
  const segments = target.slice(root.length).split(path.sep).filter(Boolean);
  for (let i = segments.length; i >= 0; i--) {
    const candidate = path.join(root, ...segments.slice(0, i));
    try {
      const real = await fs.realpath(candidate);
      return i === segments.length
        ? real
        : path.join(real, ...segments.slice(i));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }
  return target;
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
