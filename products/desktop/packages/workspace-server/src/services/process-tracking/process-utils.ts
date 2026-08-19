import { execFileSync, execSync } from "node:child_process";
import { platform } from "node:os";

const SIGKILL_GRACE_MS = 5_000;

export interface ProcessEntry {
  pid: number;
  ppid: number;
  pgid: number;
  startedAt: string;
}

export function findProcessTree(
  rootPid: number,
  processTable: readonly ProcessEntry[],
): ProcessEntry[] {
  return findProcessTreeFromIndex(
    rootPid,
    processTable,
    indexProcesses(processTable),
  );
}

function indexProcesses(
  processTable: readonly ProcessEntry[],
): Map<number, ProcessEntry[]> {
  const children = new Map<number, ProcessEntry[]>();
  for (const entry of processTable) {
    const siblings = children.get(entry.ppid) ?? [];
    siblings.push(entry);
    children.set(entry.ppid, siblings);
  }
  return children;
}

function findProcessTreeFromIndex(
  rootPid: number,
  processTable: readonly ProcessEntry[],
  children: ReadonlyMap<number, readonly ProcessEntry[]>,
): ProcessEntry[] {
  const tree: ProcessEntry[] = [];
  const visit = (pid: number): void => {
    for (const child of children.get(pid) ?? []) {
      visit(child.pid);
      tree.push(child);
    }
  };
  visit(rootPid);

  const root = processTable.find((entry) => entry.pid === rootPid);
  if (root) tree.push(root);
  return tree;
}

function snapshotUnixProcesses(): ProcessEntry[] {
  try {
    const output = execFileSync("ps", ["-axo", "pid=,ppid=,pgid=,lstart="], {
      encoding: "utf8",
    });
    return output
      .trim()
      .split("\n")
      .map((line): ProcessEntry | null => {
        const match = line.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/);
        if (!match) return null;
        return {
          pid: Number(match[1]),
          ppid: Number(match[2]),
          pgid: Number(match[3]),
          startedAt: match[4],
        };
      })
      .filter((entry): entry is ProcessEntry => entry !== null);
  } catch {
    return [];
  }
}

export function findMatchingProcessTargets(
  originalTree: readonly ProcessEntry[],
  currentProcesses: readonly ProcessEntry[],
  excludedPgid: number | undefined,
): number[] {
  const originalByPid = new Map(
    originalTree.map((entry) => [entry.pid, entry]),
  );
  const matching = currentProcesses.filter((entry) => {
    const original = originalByPid.get(entry.pid);
    return (
      original?.pgid === entry.pgid && original.startedAt === entry.startedAt
    );
  });
  const groups = new Set(
    matching
      .map((entry) => entry.pgid)
      .filter((pgid) => pgid > 0 && pgid !== excludedPgid),
  );
  return [
    ...Array.from(groups, (pgid) => -pgid),
    ...matching.map((entry) => entry.pid),
  ];
}

export interface UnixProcessKillerDeps {
  currentProcesses: () => ProcessEntry[];
  signal: (targets: readonly number[], signal: NodeJS.Signals) => void;
  schedule: (callback: () => void, delayMs: number) => void;
}

export function killUnixProcessTrees(
  rootPids: readonly number[],
  initialProcesses: readonly ProcessEntry[],
  ownPgid: number | undefined,
  deps: UnixProcessKillerDeps,
): void {
  const children = indexProcesses(initialProcesses);
  const missingRootPids: number[] = [];
  const trees = rootPids.flatMap((pid) => {
    const tree = findProcessTreeFromIndex(pid, initialProcesses, children);
    if (tree.length === 0) missingRootPids.push(pid);
    return tree;
  });
  const originalTree = Array.from(
    new Map(trees.flat().map((entry) => [entry.pid, entry])).values(),
  );
  if (originalTree.length === 0 || ownPgid === undefined) {
    deps.signal(
      rootPids.flatMap((pid) => [-pid, pid]),
      "SIGTERM",
    );
    return;
  }

  const targets = [
    ...missingRootPids.flatMap((pid) => [-pid, pid]),
    ...findMatchingProcessTargets(originalTree, initialProcesses, ownPgid),
  ];
  deps.signal(targets, "SIGTERM");
  deps.schedule(() => {
    deps.signal(
      findMatchingProcessTargets(
        originalTree,
        deps.currentProcesses(),
        ownPgid,
      ),
      "SIGKILL",
    );
  }, SIGKILL_GRACE_MS);
}

function signalTargets(
  targets: readonly number[],
  signal: NodeJS.Signals,
): void {
  for (const target of targets) {
    try {
      process.kill(target, signal);
    } catch {}
  }
}

/**
 * Kill a process and all its descendants, including children that created
 * their own process groups.
 * On Windows, we use taskkill with /T flag to kill the process tree.
 */
export function killProcessTrees(pids: readonly number[]): void {
  if (pids.length === 0) return;
  if (platform() === "win32") {
    // Windows: use taskkill with /T to kill process tree
    for (const pid of pids) {
      try {
        execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
      } catch {}
    }
  } else {
    try {
      const processes = snapshotUnixProcesses();
      const ownPgid = processes.find(
        (entry) => entry.pid === process.pid,
      )?.pgid;
      killUnixProcessTrees(pids, processes, ownPgid, {
        currentProcesses: snapshotUnixProcesses,
        signal: signalTargets,
        schedule: (callback, delayMs) => {
          setTimeout(callback, delayMs).unref();
        },
      });
    } catch {}
  }
}

export function killProcessTree(pid: number): void {
  killProcessTrees([pid]);
}

/**
 * Check if a process is alive using signal 0.
 */
export function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
