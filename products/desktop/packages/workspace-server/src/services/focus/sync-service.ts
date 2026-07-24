import fs from "node:fs/promises";
import path from "node:path";
import * as watcher from "@parcel/watcher";
import {
  getStagedDiff,
  getUnstagedDiff,
  listUntrackedFiles,
} from "@posthog/git/queries";
import { ApplyPatchSaga } from "@posthog/git/sagas/patch";
import ignore, { type Ignore } from "ignore";
import { injectable } from "inversify";

const DEBOUNCE_MS = 250;
const SUBSCRIBE_TIMEOUT_MS = 5_000;
const ALWAYS_IGNORE = [".git", ".jj", "node_modules"];
const WRITE_COOLDOWN_MS = 1_000;

interface PendingSync {
  mainToWorktree: Map<string, "copy" | "delete">;
  worktreeToMain: Map<string, "copy" | "delete">;
  timer: ReturnType<typeof setTimeout> | null;
}

@injectable()
export class FocusSyncService {
  private mainRepoPath: string | null = null;
  private worktreePath: string | null = null;
  private mainSubscription: { unsubscribe(): Promise<unknown> } | null = null;
  private worktreeSubscription: { unsubscribe(): Promise<unknown> } | null =
    null;
  private gitignore!: Ignore;
  private pending: PendingSync = {
    mainToWorktree: new Map(),
    worktreeToMain: new Map(),
    timer: null,
  };
  private syncing = false;
  private initialSyncing = false;
  private currentSyncPromise: Promise<void> | null = null;
  private recentWrites = new Map<string, number>();

  async startSync(mainRepoPath: string, worktreePath: string): Promise<void> {
    const [mainExists, worktreeExists] = await Promise.all([
      fs
        .access(mainRepoPath)
        .then(() => true)
        .catch(() => false),
      fs
        .access(worktreePath)
        .then(() => true)
        .catch(() => false),
    ]);

    if (!mainExists || !worktreeExists) {
      return;
    }

    if (this.mainSubscription || this.worktreeSubscription) {
      await this.stopSync();
    }

    this.mainRepoPath = mainRepoPath;
    this.worktreePath = worktreePath;

    await Promise.race([
      this.loadGitignore(mainRepoPath),
      new Promise<void>((resolve) => setTimeout(resolve, 2_000)),
    ]);

    this.initialSyncing = true;
    try {
      await this.copyUncommittedFiles(worktreePath, mainRepoPath);
    } finally {
      this.initialSyncing = false;
    }

    const watcherIgnore = ALWAYS_IGNORE.map((entry) => `**/${entry}/**`);

    const mainSubscribe = subscribeWithTimeout(
      watcher.subscribe(
        mainRepoPath,
        (error, events) => {
          if (error) return;
          this.handleEvents("main", events);
        },
        { ignore: watcherIgnore },
      ),
      SUBSCRIBE_TIMEOUT_MS,
    );

    const worktreeSubscribe = subscribeWithTimeout(
      watcher.subscribe(
        worktreePath,
        (error, events) => {
          if (error) return;
          this.handleEvents("worktree", events);
        },
        { ignore: watcherIgnore },
      ),
      SUBSCRIBE_TIMEOUT_MS,
    );

    this.mainSubscription = await mainSubscribe;
    this.worktreeSubscription = await worktreeSubscribe;
  }

  async stopSync(): Promise<void> {
    if (this.pending.timer) {
      clearTimeout(this.pending.timer);
      this.pending.timer = null;
    }

    if (this.currentSyncPromise) {
      await Promise.race([
        this.currentSyncPromise,
        new Promise((resolve) => setTimeout(resolve, 2_000)),
      ]);
    }

    if (
      this.pending.mainToWorktree.size > 0 ||
      this.pending.worktreeToMain.size > 0
    ) {
      await Promise.race([
        this.doFlush(),
        new Promise((resolve) => setTimeout(resolve, 2_000)),
      ]);
    }

    await this.mainSubscription?.unsubscribe();
    await this.worktreeSubscription?.unsubscribe();

    this.mainSubscription = null;
    this.worktreeSubscription = null;
    this.mainRepoPath = null;
    this.worktreePath = null;
    this.pending.mainToWorktree.clear();
    this.pending.worktreeToMain.clear();
    this.recentWrites.clear();
    this.initialSyncing = false;
  }

  async copyUncommittedFiles(srcPath: string, dstPath: string): Promise<void> {
    const [stagedPatch, unstagedPatch, untrackedList] = await Promise.all([
      getStagedDiff(srcPath).catch(() => ""),
      getUnstagedDiff(srcPath).catch(() => ""),
      listUntrackedFiles(srcPath).catch(() => []),
    ]);

    const hasStaged = stagedPatch.length > 0;
    const hasUnstaged = unstagedPatch.length > 0;
    const hasUntracked = untrackedList.length > 0;

    if (!hasStaged && !hasUnstaged && !hasUntracked) {
      return;
    }

    if (hasStaged) {
      await this.applyPatch(dstPath, stagedPatch, true).catch(() => {});
    }

    if (hasUnstaged) {
      await this.applyPatch(dstPath, unstagedPatch, false).catch(() => {});
    }

    if (hasUntracked) {
      for (const file of untrackedList) {
        const src = path.join(srcPath, file);
        const dst = path.join(dstPath, file);
        await this.copyFileDirect(src, dst);
      }
    }
  }

  private async applyPatch(
    repoPath: string,
    patch: string,
    cached: boolean,
  ): Promise<void> {
    const saga = new ApplyPatchSaga();
    const result = await saga.run({ baseDir: repoPath, patch, cached });
    if (!result.success) {
      throw new Error(`git apply failed: ${result.error}`);
    }
  }

  private async copyFileDirect(
    srcPath: string,
    dstPath: string,
  ): Promise<void> {
    try {
      const srcStat = await fs.stat(srcPath);
      if (!srcStat.isFile()) return;

      await fs.mkdir(path.dirname(dstPath), { recursive: true });
      await fs.copyFile(srcPath, dstPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async loadGitignore(repoPath: string): Promise<void> {
    this.gitignore = ignore().add(ALWAYS_IGNORE);

    try {
      const content = await fs.readFile(
        path.join(repoPath, ".gitignore"),
        "utf-8",
      );
      this.gitignore.add(content);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }

  private handleEvents(
    source: "main" | "worktree",
    events: watcher.Event[],
  ): void {
    if (this.initialSyncing) return;

    const basePath = source === "main" ? this.mainRepoPath : this.worktreePath;
    if (!basePath) return;

    const pendingMap =
      source === "main"
        ? this.pending.mainToWorktree
        : this.pending.worktreeToMain;
    const now = Date.now();

    for (const event of events) {
      const relativePath = path.relative(basePath, event.path);

      if (this.gitignore.ignores(relativePath)) {
        continue;
      }

      const lastWrite = this.recentWrites.get(event.path);
      if (lastWrite && now - lastWrite < WRITE_COOLDOWN_MS) {
        continue;
      }

      pendingMap.set(relativePath, event.type === "delete" ? "delete" : "copy");
    }

    if (this.pending.timer) {
      clearTimeout(this.pending.timer);
    }
    this.pending.timer = setTimeout(
      () => void this.flushPending(),
      DEBOUNCE_MS,
    );
  }

  private async flushPending(): Promise<void> {
    if (this.syncing) {
      this.pending.timer = setTimeout(
        () => void this.flushPending(),
        DEBOUNCE_MS,
      );
      return;
    }

    this.currentSyncPromise = this.doFlush();
    await this.currentSyncPromise;
    this.currentSyncPromise = null;
  }

  private async doFlush(): Promise<void> {
    this.syncing = true;
    this.pending.timer = null;

    try {
      if (this.pending.mainToWorktree.size > 0) {
        const operations = new Map(this.pending.mainToWorktree);
        this.pending.mainToWorktree.clear();
        await this.syncFiles("main", operations);
      }

      if (this.pending.worktreeToMain.size > 0) {
        const operations = new Map(this.pending.worktreeToMain);
        this.pending.worktreeToMain.clear();
        await this.syncFiles("worktree", operations);
      }
    } finally {
      this.syncing = false;
    }
  }

  private async syncFiles(
    source: "main" | "worktree",
    operations: Map<string, "copy" | "delete">,
  ): Promise<void> {
    const srcBase = source === "main" ? this.mainRepoPath : this.worktreePath;
    const dstBase = source === "main" ? this.worktreePath : this.mainRepoPath;

    if (!srcBase || !dstBase) return;

    for (const [relativePath, operation] of operations) {
      const srcPath = path.join(srcBase, relativePath);
      const dstPath = path.join(dstBase, relativePath);

      if (operation === "delete") {
        await this.deleteFile(dstPath);
      } else {
        await this.copyFile(srcPath, dstPath);
      }
    }
  }

  private async copyFile(srcPath: string, dstPath: string): Promise<void> {
    let srcStat: Awaited<ReturnType<typeof fs.stat>>;
    try {
      srcStat = await fs.stat(srcPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return;
      }
      throw error;
    }

    if (!srcStat.isFile()) {
      return;
    }

    try {
      const [srcContent, dstContent] = await Promise.all([
        fs.readFile(srcPath),
        fs.readFile(dstPath),
      ]);

      if (srcContent.equals(dstContent)) {
        return;
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }

    await fs.mkdir(path.dirname(dstPath), { recursive: true });
    this.recentWrites.set(dstPath, Date.now());
    await fs.copyFile(srcPath, dstPath);
  }

  private async deleteFile(filePath: string): Promise<void> {
    this.recentWrites.set(filePath, Date.now());

    try {
      await fs.rm(filePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }
}

async function subscribeWithTimeout<
  T extends { unsubscribe(): Promise<unknown> },
>(subscribePromise: Promise<T>, timeoutMs: number): Promise<T | null> {
  let timeoutHandle!: ReturnType<typeof setTimeout>;
  const timeoutPromise = new Promise<null>((resolve) => {
    timeoutHandle = setTimeout(() => resolve(null), timeoutMs);
  });

  const result = await Promise.race([subscribePromise, timeoutPromise]);
  clearTimeout(timeoutHandle);

  if (result === null) {
    subscribePromise.then((subscription) => {
      void subscription.unsubscribe().catch(() => {});
    });
    return null;
  }

  return result;
}
