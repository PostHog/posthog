import { execFileSync } from "node:child_process";
import { platform } from "node:os";

const SIGKILL_GRACE_MS = 5_000;

interface UnixProcess {
  pid: number;
  parentPid: number;
  startedAt: string;
}

function readUnixProcessTable(): Map<number, UnixProcess> | undefined {
  let processTable: string;
  try {
    processTable = execFileSync("ps", ["-ax", "-o", "pid=,ppid=,lstart="], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch {
    return undefined;
  }

  const processes = new Map<number, UnixProcess>();
  for (const line of processTable.split("\n")) {
    const match = line.match(/^\s*(\d+)\s+(\d+)\s+(.+?)\s*$/);
    if (!match) continue;
    const pid = Number.parseInt(match[1], 10);
    const parentPid = Number.parseInt(match[2], 10);
    processes.set(pid, { pid, parentPid, startedAt: match[3] });
  }
  return processes;
}

function getUnixProcessTree(rootPid: number): UnixProcess[] {
  const processes = readUnixProcessTable();
  if (!processes) {
    return [{ pid: rootPid, parentPid: 0, startedAt: "" }];
  }

  const childrenByParent = new Map<number, number[]>();
  for (const processInfo of processes.values()) {
    const { pid, parentPid } = processInfo;
    const children = childrenByParent.get(parentPid) ?? [];
    children.push(pid);
    childrenByParent.set(parentPid, children);
  }

  const processTree: UnixProcess[] = [];
  const visited = new Set<number>();
  const addProcessTree = (pid: number): void => {
    if (visited.has(pid)) return;
    visited.add(pid);
    for (const childPid of childrenByParent.get(pid) ?? []) {
      addProcessTree(childPid);
    }
    processTree.push(
      processes.get(pid) ?? { pid, parentPid: 0, startedAt: "" },
    );
  };
  addProcessTree(rootPid);
  return processTree;
}

export function killProcessTree(pid: number): void {
  try {
    if (platform() === "win32") {
      execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      const processTree = getUnixProcessTree(pid);
      let sent = false;
      for (const processInfo of processTree) {
        try {
          process.kill(processInfo.pid, "SIGTERM");
          sent = true;
        } catch {}
      }

      if (!sent) return;

      setTimeout(() => {
        const currentProcesses = readUnixProcessTable();
        if (!currentProcesses) return;
        for (const processInfo of processTree) {
          if (
            currentProcesses.get(processInfo.pid)?.startedAt !==
            processInfo.startedAt
          ) {
            continue;
          }
          try {
            process.kill(processInfo.pid, "SIGKILL");
          } catch {}
        }
      }, SIGKILL_GRACE_MS).unref();
    }
  } catch {}
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
