import { execFileSync } from "node:child_process";
import { platform } from "node:os";

const SIGKILL_GRACE_MS = 5_000;

function getUnixProcessTreePids(rootPid: number): number[] {
  let processTable: string;
  try {
    processTable = execFileSync("ps", ["-ax", "-o", "pid=,ppid="], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch {
    return [rootPid];
  }

  const childrenByParent = new Map<number, number[]>();
  for (const line of processTable.split("\n")) {
    const [pidText, parentPidText] = line.trim().split(/\s+/);
    const pid = Number.parseInt(pidText, 10);
    const parentPid = Number.parseInt(parentPidText, 10);
    if (Number.isNaN(pid) || Number.isNaN(parentPid)) continue;
    const children = childrenByParent.get(parentPid) ?? [];
    children.push(pid);
    childrenByParent.set(parentPid, children);
  }

  const processTreePids: number[] = [];
  const visited = new Set<number>();
  const addProcessTree = (pid: number): void => {
    if (visited.has(pid)) return;
    visited.add(pid);
    for (const childPid of childrenByParent.get(pid) ?? []) {
      addProcessTree(childPid);
    }
    processTreePids.push(pid);
  };
  addProcessTree(rootPid);
  return processTreePids;
}

/**
 * Descendants can create new process groups, so a group signal can leave task
 * commands running after the app exits.
 */
export function killProcessTree(pid: number): void {
  try {
    if (platform() === "win32") {
      execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      const processTreePids = getUnixProcessTreePids(pid);
      let sent = false;
      for (const targetPid of processTreePids) {
        try {
          process.kill(targetPid, "SIGTERM");
          sent = true;
        } catch {}
      }

      if (!sent) return;

      // Keep this timer detached from app shutdown because descendants can ignore SIGTERM.
      setTimeout(() => {
        for (const targetPid of processTreePids) {
          try {
            process.kill(targetPid, "SIGKILL");
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
