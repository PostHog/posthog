import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import * as watcher from "@parcel/watcher";
import { injectable } from "inversify";
import type { FileWatcherEvent, WatcherEvent } from "./schemas";

export type WatchOptions = {
  ignore?: string[];
};

const IGNORE_PATTERNS = ["**/node_modules/**", "**/.git/**", "**/.jj/**"];

// Ignore patterns for the git-dir watches. Linked worktrees share the main
// repo's `.git` as their `commondir`, so every worktree's commondir watch sees
// the whole `.git/worktrees/` admin subtree — including sibling worktrees'
// HEAD/index files. Without this, creating or mutating one worktree wakes every
// other worktree's watcher (each firing a branch re-check + renderer
// invalidation), so the per-event cost grows linearly with the number of
// worktrees. A worktree's own admin dir is watched directly as its `gitDir`
// (rooted inside `worktrees/<name>`, where this pattern matches nothing), so
// excluding the subtree from the commondir watch drops only cross-worktree
// noise; shared refs (`refs/heads`, `packed-refs`) live outside `worktrees/`
// and are still observed.
const GIT_IGNORE_PATTERNS = ["**/worktrees/**"];
export const DEBOUNCE_MS = 500;
// Upper bound on how long working-tree events may be coalesced. The trailing
// debounce resets on every event, so an agent writing continuously would other-
// wise never trip it until it paused, freezing the diff panel/stats mid-run.
// The max-wait forces a flush at least this often during sustained activity so
// the UI keeps advancing while the agent works.
export const MAX_WAIT_MS = 1000;
const BULK_THRESHOLD = 100;

const dirname = (p: string): string => {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i <= 0 ? p : p.slice(0, i);
};

const isRelevantGitEvent = (p: string): boolean =>
  p.endsWith("/HEAD") ||
  p.endsWith("/index") ||
  p.endsWith("/MERGE_HEAD") ||
  p.endsWith("/CHERRY_PICK_HEAD") ||
  p.endsWith("/REVERT_HEAD") ||
  p.includes("/rebase-merge") ||
  p.includes("/rebase-apply") ||
  p.includes("/refs/heads/");

interface Pending {
  dirs: Set<string>;
  files: Set<string>;
  deletes: Set<string>;
}

const createPending = (): Pending => ({
  dirs: new Set(),
  files: new Set(),
  deletes: new Set(),
});

export const accumulateFsEvents = (
  pending: Pending,
  events: WatcherEvent[],
): void => {
  for (const event of events) {
    pending.dirs.add(dirname(event.path));
    if (event.type === "delete") pending.deletes.add(event.path);
    else pending.files.add(event.path);
  }
};

export const drainPending = (
  repoPath: string,
  pending: Pending,
): FileWatcherEvent[] => {
  const totalChanges = pending.files.size + pending.deletes.size;
  const out: FileWatcherEvent[] = [];
  if (totalChanges === 0 && pending.dirs.size === 0) return out;

  if (totalChanges > 0) {
    out.push({ kind: "working-tree-changed", repoPath });
  }
  if (totalChanges <= BULK_THRESHOLD) {
    for (const dirPath of pending.dirs)
      out.push({ kind: "directory-changed", repoPath, dirPath });
    for (const filePath of pending.files)
      out.push({ kind: "file-changed", repoPath, filePath });
    for (const filePath of pending.deletes)
      out.push({ kind: "file-deleted", repoPath, filePath });
  }
  pending.dirs.clear();
  pending.files.clear();
  pending.deletes.clear();
  return out;
};

@injectable()
export class WatcherService {
  async *watch(
    dirPath: string,
    options: WatchOptions,
    signal?: AbortSignal,
  ): AsyncGenerator<WatcherEvent[]> {
    const effectiveSignal = signal ?? new AbortController().signal;
    const queue: WatcherEvent[][] = [];
    let resolve: ((value: WatcherEvent[][] | null) => void) | null = null;
    let closed = false;

    const push = (events: WatcherEvent[]) => {
      if (closed) return;
      queue.push(events);
      if (resolve) {
        const r = resolve;
        resolve = null;
        r(queue.splice(0));
      }
    };

    const close = () => {
      if (closed) return;
      closed = true;
      if (resolve) {
        const r = resolve;
        resolve = null;
        r(null);
      }
    };

    const subscription = await watcher.subscribe(
      dirPath,
      (err, events) => {
        if (err) {
          if (!existsSync(dirPath)) close();
          return;
        }
        push(events);
      },
      { ignore: options.ignore },
    );

    const onAbort = () => close();
    effectiveSignal.addEventListener("abort", onAbort, { once: true });

    try {
      while (!closed) {
        if (queue.length > 0) {
          for (const batch of queue.splice(0)) yield batch;
          continue;
        }
        const next = await new Promise<WatcherEvent[][] | null>((r) => {
          resolve = r;
        });
        if (next === null) break;
        for (const batch of next) yield batch;
      }
    } finally {
      effectiveSignal.removeEventListener("abort", onAbort);
      await subscription.unsubscribe().catch(() => {});
    }
  }

  async *watchRepo(
    repoPath: string,
    signal?: AbortSignal,
  ): AsyncGenerator<FileWatcherEvent> {
    const fileEvents = this.watch(
      repoPath,
      { ignore: IGNORE_PATTERNS },
      signal,
    );
    const { gitDir, commonDir } = await this.resolveGitDirs(repoPath);

    const pending = createPending();
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let maxWaitTimer: ReturnType<typeof setTimeout> | null = null;
    const outQueue: FileWatcherEvent[] = [];
    let outResolve: ((next: FileWatcherEvent[] | null) => void) | null = null;
    let outClosed = false;

    const pushOut = (events: FileWatcherEvent[]) => {
      if (outClosed || events.length === 0) return;
      outQueue.push(...events);
      if (outResolve) {
        const r = outResolve;
        outResolve = null;
        r(outQueue.splice(0));
      }
    };

    const closeOut = () => {
      if (outClosed) return;
      outClosed = true;
      if (outResolve) {
        const r = outResolve;
        outResolve = null;
        r(null);
      }
    };

    const flushPending = () => {
      if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      if (maxWaitTimer) {
        clearTimeout(maxWaitTimer);
        maxWaitTimer = null;
      }
      pushOut(drainPending(repoPath, pending));
    };

    const fileLoop = (async () => {
      try {
        for await (const batch of fileEvents) {
          accumulateFsEvents(pending, batch);
          // Trailing debounce: coalesce a burst and emit once it goes quiet.
          if (debounceTimer) clearTimeout(debounceTimer);
          debounceTimer = setTimeout(flushPending, DEBOUNCE_MS);
          // Max-wait: bound the coalescing so sustained activity still flushes.
          if (!maxWaitTimer)
            maxWaitTimer = setTimeout(flushPending, MAX_WAIT_MS);
        }
      } finally {
        if (debounceTimer) clearTimeout(debounceTimer);
        if (maxWaitTimer) clearTimeout(maxWaitTimer);
        closeOut();
      }
    })();

    const gitLoops: Promise<void>[] = [];
    const gitDirs = [
      gitDir,
      commonDir && commonDir !== gitDir ? commonDir : null,
    ].filter((d): d is string => !!d);
    for (const dir of gitDirs) {
      gitLoops.push(
        (async () => {
          for await (const batch of this.watch(
            dir,
            { ignore: GIT_IGNORE_PATTERNS },
            signal,
          )) {
            if (batch.some((e) => isRelevantGitEvent(e.path))) {
              pushOut([{ kind: "git-state-changed", repoPath }]);
            }
          }
        })().catch(() => {}),
      );
    }

    signal?.addEventListener("abort", closeOut, { once: true });

    try {
      while (!outClosed) {
        if (outQueue.length > 0) {
          for (const event of outQueue.splice(0)) yield event;
          continue;
        }
        const next = await new Promise<FileWatcherEvent[] | null>((r) => {
          outResolve = r;
        });
        if (next === null) break;
        for (const event of next) yield event;
      }
    } finally {
      signal?.removeEventListener("abort", closeOut);
      closeOut();
      await fileLoop.catch(() => {});
      await Promise.all(gitLoops).catch(() => {});
    }
  }

  async resolveGitDirs(
    repoPath: string,
  ): Promise<{ gitDir: string | null; commonDir: string | null }> {
    const gitDir = await this.resolveGitDir(repoPath);
    const commonDir = gitDir ? await this.resolveCommonDir(gitDir) : null;
    return { gitDir, commonDir };
  }

  async resolveGitDir(repoPath: string): Promise<string | null> {
    try {
      const gitPath = path.join(repoPath, ".git");
      const stat = await fs.stat(gitPath);
      if (stat.isDirectory()) return gitPath;

      const content = await fs.readFile(gitPath, "utf-8");
      const match = content.match(/gitdir:\s*(.+)/);
      if (!match) return null;
      return path.resolve(repoPath, match[1].trim());
    } catch {
      return null;
    }
  }

  async resolveCommonDir(gitDir: string): Promise<string | null> {
    try {
      const commonDirFile = path.join(gitDir, "commondir");
      const content = await fs.readFile(commonDirFile, "utf-8");
      const resolved = path.resolve(gitDir, content.trim());
      return resolved === gitDir ? null : resolved;
    } catch {
      return null;
    }
  }
}
