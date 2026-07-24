import { afterEach, describe, expect, it, vi } from "vitest";
import type { FileWatcherEvent, WatcherEvent } from "./schemas";
import { DEBOUNCE_MS, MAX_WAIT_MS, WatcherService } from "./service";

afterEach(() => {
  vi.useRealTimers();
});

/**
 * Records every `watch()` call so we can assert what each watched directory is
 * told to ignore, then drains the generator so the loops shut down cleanly.
 */
async function collectWatchCalls(
  repoPath: string,
  gitDirs: {
    gitDir: string | null;
    commonDir: string | null;
  },
): Promise<Array<{ dir: string; ignore?: string[] }>> {
  const service = new WatcherService();
  const calls: Array<{ dir: string; ignore?: string[] }> = [];

  vi.spyOn(service, "resolveGitDirs").mockResolvedValue(gitDirs);
  // Empty generators end the file/git loops immediately, so watchRepo settles
  // after recording the subscribe targets.
  vi.spyOn(service, "watch").mockImplementation(
    // biome-ignore lint/correctness/useYield: intentionally empty generator
    async function* (
      dir: string,
      options: { ignore?: string[] },
    ): AsyncGenerator<WatcherEvent[]> {
      calls.push({ dir, ignore: options.ignore });
    },
  );

  const controller = new AbortController();
  const gen = service.watchRepo(repoPath, controller.signal);
  await gen.next();
  controller.abort();
  await gen.return?.(undefined);

  return calls;
}

describe("WatcherService.watchRepo ignore patterns", () => {
  it("excludes the cross-worktree admin subtree from the linked worktree's git watches", async () => {
    const repoPath = "/repo/.worktrees/feature/myrepo";
    const calls = await collectWatchCalls(repoPath, {
      gitDir: "/main/.git/worktrees/feature",
      commonDir: "/main/.git",
    });

    // The shared commondir is watched but must skip `.git/worktrees/**`, so a
    // sibling worktree's HEAD/index churn (e.g. creating a new worktree) no
    // longer wakes this worktree's watcher.
    const commonDirCall = calls.find((c) => c.dir === "/main/.git");
    expect(commonDirCall?.ignore).toEqual(["**/worktrees/**"]);

    // The worktree's own gitDir is rooted inside `worktrees/<name>`, where the
    // pattern matches nothing, so its own HEAD changes are still observed.
    const gitDirCall = calls.find(
      (c) => c.dir === "/main/.git/worktrees/feature",
    );
    expect(gitDirCall?.ignore).toEqual(["**/worktrees/**"]);

    // The working tree keeps its own ignores (node_modules/.git/.jj).
    const workingTreeCall = calls.find((c) => c.dir === repoPath);
    expect(workingTreeCall?.ignore).toContain("**/node_modules/**");
    expect(workingTreeCall?.ignore).not.toContain("**/worktrees/**");
  });

  it("watches a non-worktree repo's git dir once with the worktrees ignore", async () => {
    const repoPath = "/main";
    const calls = await collectWatchCalls(repoPath, {
      gitDir: "/main/.git",
      commonDir: null,
    });

    const gitDirCalls = calls.filter((c) => c.dir === "/main/.git");
    expect(gitDirCalls).toHaveLength(1);
    expect(gitDirCalls[0]?.ignore).toEqual(["**/worktrees/**"]);
  });
});

interface ManualGen {
  gen: AsyncGenerator<WatcherEvent[]>;
  push: (batch: WatcherEvent[]) => void;
  end: () => void;
}

/** A watch generator whose batches the test emits on demand. */
function manualGen(): ManualGen {
  const queue: WatcherEvent[][] = [];
  let notify: (() => void) | null = null;
  let ended = false;

  const wake = () => {
    if (notify) {
      const n = notify;
      notify = null;
      n();
    }
  };

  async function* generate(): AsyncGenerator<WatcherEvent[]> {
    while (true) {
      while (queue.length > 0) yield queue.shift() as WatcherEvent[];
      if (ended) return;
      await new Promise<void>((resolve) => {
        notify = resolve;
      });
    }
  }

  return {
    gen: generate(),
    push(batch) {
      queue.push(batch);
      wake();
    },
    end() {
      ended = true;
      wake();
    },
  };
}

/** Drives watchRepo with a controllable working-tree watch and no git dirs. */
function startWatch(wt: ManualGen): AsyncGenerator<FileWatcherEvent> {
  const service = new WatcherService();
  vi.spyOn(service, "resolveGitDirs").mockResolvedValue({
    gitDir: null,
    commonDir: null,
  });
  // With no git dirs resolved, the only watch() call is the working-tree one.
  vi.spyOn(service, "watch").mockReturnValue(wt.gen);
  return service.watchRepo("/repo", new AbortController().signal);
}

/**
 * A working-tree change also emits per-file/dir events (below BULK_THRESHOLD);
 * the coalesced `working-tree-changed` is the one that drives invalidation, so
 * the debounce tests assert on just those.
 */
const workingTreeChanges = (events: FileWatcherEvent[]): FileWatcherEvent[] =>
  events.filter((e) => e.kind === "working-tree-changed");

/** Consumes watchRepo in the background, collecting every emitted event. */
function drainEvents(out: AsyncGenerator<FileWatcherEvent>): {
  events: FileWatcherEvent[];
  done: Promise<void>;
} {
  const events: FileWatcherEvent[] = [];
  const done = (async () => {
    for await (const ev of out) events.push(ev);
  })();
  return { events, done };
}

describe("WatcherService.watchRepo debounce", () => {
  it("coalesces a burst and emits once it goes quiet", async () => {
    vi.useFakeTimers();
    const wt = manualGen();
    const { events, done } = drainEvents(startWatch(wt));
    // Let watchRepo settle past resolveGitDirs and start its file loop.
    await vi.advanceTimersByTimeAsync(0);

    wt.push([{ type: "update", path: "/repo/a.ts" }]);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 1);
    expect(events).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1);
    expect(workingTreeChanges(events)).toEqual([
      { kind: "working-tree-changed", repoPath: "/repo" },
    ]);

    wt.end();
    await done;
  });

  it("flushes during sustained activity via the max-wait", async () => {
    vi.useFakeTimers();
    const wt = manualGen();
    const { events, done } = drainEvents(startWatch(wt));
    await vi.advanceTimersByTimeAsync(0);

    // Push faster than the trailing debounce so its quiet-period timer keeps
    // resetting and can never fire on its own; only the max-wait can flush.
    const step = DEBOUNCE_MS - 100;
    let elapsed = 0;
    while (elapsed + step < MAX_WAIT_MS) {
      wt.push([{ type: "update", path: `/repo/f${elapsed}.ts` }]);
      await vi.advanceTimersByTimeAsync(step);
      elapsed += step;
    }
    // Continuously active for longer than the debounce window but not yet the
    // max-wait: the trailing debounce alone would not have emitted anything.
    expect(elapsed).toBeGreaterThan(DEBOUNCE_MS);
    expect(events).toHaveLength(0);

    // Crossing MAX_WAIT_MS forces a flush despite the ongoing activity.
    wt.push([{ type: "update", path: "/repo/final.ts" }]);
    await vi.advanceTimersByTimeAsync(MAX_WAIT_MS - elapsed + 1);
    expect(workingTreeChanges(events)).toEqual([
      { kind: "working-tree-changed", repoPath: "/repo" },
    ]);

    wt.end();
    await done;
  });
});
