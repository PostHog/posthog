import { execSync } from "node:child_process";
import { platform } from "node:os";

const SIGKILL_GRACE_MS = 5_000;

/**
 * Kill a process and all its children by killing the process group.
 * On Unix, we use process.kill(-pid) to kill the entire process group.
 * On Windows, we use taskkill with /T flag to kill the process tree.
 */
export function killProcessTree(pid: number): void {
  try {
    if (platform() === "win32") {
      // Windows: use taskkill with /T to kill process tree
      execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
    } else {
      // SIGTERM the process group first, fall back to individual process
      let sent = false;
      for (const target of [-pid, pid]) {
        try {
          process.kill(target, "SIGTERM");
          sent = true;
          break;
        } catch {}
      }

      if (!sent) return;

      // Force kill after a grace period — unref so the timer doesn't delay app exit.
      // We skip the liveness check since isProcessAlive only tests the group leader;
      // orphaned children in the same group would be missed. The catch blocks
      // handle ESRCH if everything already exited.
      setTimeout(() => {
        for (const target of [-pid, pid]) {
          try {
            process.kill(target, "SIGKILL");
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
