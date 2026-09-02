import { exec } from "node:child_process";
import { platform } from "node:os";
import { promisify } from "node:util";
import { injectable, preDestroy } from "inversify";
import { isProcessAlive, killProcessTree } from "./process-utils";
import type {
  DiscoveredProcess,
  ProcessCategory,
  ProcessSnapshot,
  TrackedProcess,
} from "./schemas";

const execAsync = promisify(exec);

export type {
  DiscoveredProcess,
  ProcessCategory,
  ProcessSnapshot,
  TrackedProcess,
};

@injectable()
export class ProcessTrackingService {
  private _isShuttingDown = false;

  get isShuttingDown(): boolean {
    return this._isShuttingDown;
  }

  private processes = new Map<number, TrackedProcess>();
  private taskProcesses = new Map<string, Set<number>>();

  register(
    pid: number,
    category: ProcessCategory,
    label: string,
    metadata?: Record<string, string>,
    taskId?: string,
  ): void {
    this.removeFromTaskIndex(pid);

    this.processes.set(pid, {
      pid,
      category,
      label,
      registeredAt: Date.now(),
      taskId,
      metadata,
    });

    if (taskId) {
      let pids = this.taskProcesses.get(taskId);
      if (!pids) {
        pids = new Set();
        this.taskProcesses.set(taskId, pids);
      }
      pids.add(pid);
    }
  }

  unregister(pid: number, _reason: string): void {
    const proc = this.processes.get(pid);
    if (proc) {
      this.removeFromTaskIndex(pid);
      this.processes.delete(pid);
    }
  }

  private removeFromTaskIndex(pid: number): void {
    const proc = this.processes.get(pid);
    if (proc?.taskId) {
      const pids = this.taskProcesses.get(proc.taskId);
      if (pids) {
        pids.delete(pid);
        if (pids.size === 0) {
          this.taskProcesses.delete(proc.taskId);
        }
      }
    }
  }

  getAll(): TrackedProcess[] {
    return Array.from(this.processes.values());
  }

  getByCategory(category: ProcessCategory): TrackedProcess[] {
    return this.getAll().filter((p) => p.category === category);
  }

  async getSnapshot(includeDiscovered = false): Promise<ProcessSnapshot> {
    for (const [pid] of this.processes) {
      if (!isProcessAlive(pid)) {
        this.unregister(pid, "pruned-dead");
      }
    }

    const tracked: Record<ProcessCategory, TrackedProcess[]> = {
      shell: [],
      agent: [],
      child: [],
    };

    for (const proc of this.processes.values()) {
      tracked[proc.category].push(proc);
    }

    const snapshot: ProcessSnapshot = {
      tracked,
      timestamp: Date.now(),
    };

    if (includeDiscovered) {
      snapshot.discovered = await this.discoverChildren();
    }

    return snapshot;
  }

  async discoverChildren(): Promise<DiscoveredProcess[]> {
    if (platform() === "win32") {
      return [];
    }

    const appPid = process.pid;

    let stdout: string;
    try {
      const result = await execAsync(
        `ps -eo pid,ppid,comm --no-headers 2>/dev/null || ps -eo pid,ppid,comm`,
      );
      stdout = result.stdout;
    } catch {
      return [];
    }

    const allProcesses: { pid: number; ppid: number; command: string }[] = [];

    for (const line of stdout.trim().split("\n")) {
      const parts = line.trim().split(/\s+/);
      if (parts.length >= 3) {
        const pid = Number.parseInt(parts[0], 10);
        const ppid = Number.parseInt(parts[1], 10);
        const command = parts.slice(2).join(" ");
        if (!Number.isNaN(pid) && !Number.isNaN(ppid)) {
          allProcesses.push({ pid, ppid, command });
        }
      }
    }

    const descendants = new Set<number>();
    const findDescendants = (parentPid: number): void => {
      for (const p of allProcesses) {
        if (p.ppid === parentPid && !descendants.has(p.pid)) {
          descendants.add(p.pid);
          findDescendants(p.pid);
        }
      }
    };

    findDescendants(appPid);

    const trackedPids = new Set(this.processes.keys());
    const discovered: DiscoveredProcess[] = [];

    for (const p of allProcesses) {
      if (descendants.has(p.pid)) {
        discovered.push({
          pid: p.pid,
          ppid: p.ppid,
          command: p.command,
          tracked: trackedPids.has(p.pid),
        });
      }
    }

    return discovered;
  }

  isAlive(pid: number): boolean {
    return isProcessAlive(pid);
  }

  kill(pid: number): void {
    killProcessTree(pid);
    this.unregister(pid, "killed");
  }

  getByTaskId(taskId: string): TrackedProcess[] {
    const pids = this.taskProcesses.get(taskId);
    if (!pids) return [];
    return Array.from(pids)
      .map((pid) => this.processes.get(pid))
      .filter((p): p is TrackedProcess => p !== undefined);
  }

  killByCategory(category: ProcessCategory): void {
    const procs = this.getByCategory(category);
    for (const proc of procs) {
      this.kill(proc.pid);
    }
  }

  killByTaskId(taskId: string): void {
    const procs = this.getByTaskId(taskId);
    for (const proc of procs) {
      this.kill(proc.pid);
    }
  }

  @preDestroy()
  killAll(): void {
    this._isShuttingDown = true;

    for (const proc of this.processes.values()) {
      killProcessTree(proc.pid);
    }
    this.processes.clear();
    this.taskProcesses.clear();
  }
}
