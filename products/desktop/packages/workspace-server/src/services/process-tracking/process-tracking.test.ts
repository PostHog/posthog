import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPlatform = vi.hoisted(() => vi.fn(() => "darwin"));
const mockIsProcessAlive = vi.hoisted(() => vi.fn((_pid: number) => true));
const mockKillProcessTree = vi.hoisted(() => vi.fn());
const mockExecAsync = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", () => ({
  exec: vi.fn(),
  default: { exec: vi.fn() },
}));

vi.mock("node:util", () => ({
  promisify: () => mockExecAsync,
  default: { promisify: () => mockExecAsync },
}));

vi.mock("node:os", () => ({
  platform: mockPlatform,
  default: { platform: mockPlatform },
}));

vi.mock("./process-utils", () => ({
  isProcessAlive: mockIsProcessAlive,
  killProcessTree: mockKillProcessTree,
}));

import { ProcessTrackingService } from "./process-tracking";

function mockExecResolves(stdout: string): void {
  mockExecAsync.mockResolvedValueOnce({ stdout, stderr: "" });
}

function mockExecRejects(error: Error): void {
  mockExecAsync.mockRejectedValueOnce(error);
}

describe("ProcessTrackingService", () => {
  let service: ProcessTrackingService;

  beforeEach(() => {
    vi.clearAllMocks();
    mockPlatform.mockReturnValue("darwin");
    mockIsProcessAlive.mockReturnValue(true);
    service = new ProcessTrackingService();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("register", () => {
    it("tracks a process", () => {
      service.register(1234, "shell", "shell:session-1");

      const all = service.getAll();
      expect(all).toHaveLength(1);
      expect(all[0]).toMatchObject({
        pid: 1234,
        category: "shell",
        label: "shell:session-1",
      });
    });

    it("stores metadata when provided", () => {
      service.register(1234, "agent", "agent:run-1", {
        taskId: "task-abc",
      });

      const all = service.getAll();
      expect(all[0].metadata).toEqual({ taskId: "task-abc" });
    });

    it("sets registeredAt timestamp", () => {
      const before = Date.now();
      service.register(1234, "shell", "test");
      const after = Date.now();

      const proc = service.getAll()[0];
      expect(proc.registeredAt).toBeGreaterThanOrEqual(before);
      expect(proc.registeredAt).toBeLessThanOrEqual(after);
    });

    it("overwrites an existing entry for the same PID", () => {
      service.register(1234, "shell", "first");
      service.register(1234, "agent", "second");

      const all = service.getAll();
      expect(all).toHaveLength(1);
      expect(all[0].category).toBe("agent");
      expect(all[0].label).toBe("second");
    });
  });

  describe("unregister", () => {
    it("removes a tracked process", () => {
      service.register(1234, "shell", "test");
      service.unregister(1234, "exited");

      expect(service.getAll()).toHaveLength(0);
    });

    it("does nothing for an unknown PID", () => {
      service.register(1234, "shell", "test");
      service.unregister(9999, "unknown");

      expect(service.getAll()).toHaveLength(1);
    });
  });

  describe("getAll", () => {
    it("returns empty array when nothing is tracked", () => {
      expect(service.getAll()).toEqual([]);
    });

    it("returns all tracked processes", () => {
      service.register(1, "shell", "s1");
      service.register(2, "agent", "a1");
      service.register(3, "child", "c1");

      expect(service.getAll()).toHaveLength(3);
    });
  });

  describe("getByCategory", () => {
    beforeEach(() => {
      service.register(1, "shell", "s1");
      service.register(2, "shell", "s2");
      service.register(3, "agent", "a1");
      service.register(4, "child", "c1");
    });

    it("filters by shell", () => {
      const shells = service.getByCategory("shell");
      expect(shells).toHaveLength(2);
      expect(shells.map((p) => p.pid)).toEqual([1, 2]);
    });

    it("filters by agent", () => {
      const agents = service.getByCategory("agent");
      expect(agents).toHaveLength(1);
      expect(agents[0].pid).toBe(3);
    });

    it("returns empty for category with no entries", () => {
      service.unregister(4, "gone");
      expect(service.getByCategory("child")).toEqual([]);
    });
  });

  describe("getSnapshot", () => {
    it("groups tracked processes by category", async () => {
      service.register(1, "shell", "s1");
      service.register(2, "agent", "a1");
      service.register(3, "child", "c1");

      const snapshot = await service.getSnapshot();

      expect(snapshot.tracked.shell).toHaveLength(1);
      expect(snapshot.tracked.agent).toHaveLength(1);
      expect(snapshot.tracked.child).toHaveLength(1);
      expect(snapshot.timestamp).toBeGreaterThan(0);
      expect(snapshot.discovered).toBeUndefined();
    });

    it("prunes dead PIDs before returning", async () => {
      service.register(1, "shell", "alive");
      service.register(2, "shell", "dead");

      mockIsProcessAlive.mockImplementation((pid: number) => pid === 1);

      const snapshot = await service.getSnapshot();

      expect(snapshot.tracked.shell).toHaveLength(1);
      expect(snapshot.tracked.shell[0].pid).toBe(1);
      expect(service.getAll()).toHaveLength(1);
    });

    it("includes discovered processes when requested", async () => {
      mockExecResolves(
        `  100  ${process.pid}  /bin/bash\n  200  100  node server.js\n`,
      );

      service.register(100, "shell", "tracked-shell");

      const snapshot = await service.getSnapshot(true);

      expect(snapshot.discovered).toBeDefined();
      expect(snapshot.discovered?.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("discoverChildren", () => {
    it("returns empty on Windows", async () => {
      mockPlatform.mockReturnValue("win32");

      const result = await service.discoverChildren();

      expect(result).toEqual([]);
      expect(mockExecAsync).not.toHaveBeenCalled();
    });

    it("finds direct children of the app", async () => {
      const appPid = process.pid;
      mockExecResolves(
        [
          `  ${appPid + 1}  ${appPid}  /bin/bash`,
          `  ${appPid + 2}  ${appPid}  node agent.js`,
          `  9999  1  /sbin/launchd`,
        ].join("\n"),
      );

      const result = await service.discoverChildren();

      expect(result).toHaveLength(2);
      expect(result.map((p) => p.pid)).toContain(appPid + 1);
      expect(result.map((p) => p.pid)).toContain(appPid + 2);
    });

    it("finds nested descendants recursively", async () => {
      const appPid = process.pid;
      const child = appPid + 1;
      const grandchild = appPid + 2;

      mockExecResolves(
        [
          `  ${child}  ${appPid}  /bin/bash`,
          `  ${grandchild}  ${child}  node server.js`,
        ].join("\n"),
      );

      const result = await service.discoverChildren();

      expect(result).toHaveLength(2);
      expect(result.find((p) => p.pid === grandchild)).toBeDefined();
    });

    it("marks tracked PIDs as tracked", async () => {
      const appPid = process.pid;
      const childPid = appPid + 1;

      mockExecResolves(`  ${childPid}  ${appPid}  /bin/bash\n`);

      service.register(childPid, "shell", "known");

      const result = await service.discoverChildren();

      expect(result).toHaveLength(1);
      expect(result[0].tracked).toBe(true);
    });

    it("marks untracked PIDs as not tracked", async () => {
      const appPid = process.pid;

      mockExecResolves(`  ${appPid + 1}  ${appPid}  mystery-process\n`);

      const result = await service.discoverChildren();

      expect(result).toHaveLength(1);
      expect(result[0].tracked).toBe(false);
    });

    it("returns empty when exec fails", async () => {
      mockExecRejects(new Error("ps failed"));

      const result = await service.discoverChildren();

      expect(result).toEqual([]);
    });

    it("does not include processes that are not descendants", async () => {
      mockExecResolves(`  9999  1  /sbin/launchd\n  8888  9999  some-other\n`);

      const result = await service.discoverChildren();

      expect(result).toEqual([]);
    });
  });

  describe("isAlive", () => {
    it("delegates to isProcessAlive", () => {
      mockIsProcessAlive.mockReturnValue(true);
      expect(service.isAlive(1234)).toBe(true);

      mockIsProcessAlive.mockReturnValue(false);
      expect(service.isAlive(1234)).toBe(false);

      expect(mockIsProcessAlive).toHaveBeenCalledWith(1234);
    });
  });

  describe("kill", () => {
    it("kills the process tree and unregisters", () => {
      service.register(1234, "shell", "test");

      service.kill(1234);

      expect(mockKillProcessTree).toHaveBeenCalledWith(1234);
      expect(service.getAll()).toHaveLength(0);
    });

    it("still calls killProcessTree for untracked PIDs", () => {
      service.kill(9999);

      expect(mockKillProcessTree).toHaveBeenCalledWith(9999);
    });
  });

  describe("killByCategory", () => {
    it("kills all processes in the given category", () => {
      service.register(1, "shell", "s1");
      service.register(2, "shell", "s2");
      service.register(3, "agent", "a1");

      service.killByCategory("shell");

      expect(mockKillProcessTree).toHaveBeenCalledWith(1);
      expect(mockKillProcessTree).toHaveBeenCalledWith(2);
      expect(mockKillProcessTree).not.toHaveBeenCalledWith(3);
      expect(service.getByCategory("shell")).toHaveLength(0);
      expect(service.getByCategory("agent")).toHaveLength(1);
    });

    it("does nothing when no processes in category", () => {
      service.register(1, "agent", "a1");

      service.killByCategory("shell");

      expect(mockKillProcessTree).not.toHaveBeenCalled();
      expect(service.getAll()).toHaveLength(1);
    });
  });

  describe("getByTaskId", () => {
    it("returns processes for a given taskId", () => {
      service.register(1, "agent", "a1", undefined, "task-1");
      service.register(2, "agent", "a2", undefined, "task-1");
      service.register(3, "agent", "a3", undefined, "task-2");

      const result = service.getByTaskId("task-1");
      expect(result).toHaveLength(2);
      expect(result.map((p) => p.pid)).toEqual([1, 2]);
    });

    it("returns empty for unknown taskId", () => {
      service.register(1, "agent", "a1", undefined, "task-1");

      expect(service.getByTaskId("task-999")).toEqual([]);
    });

    it("returns empty for processes without taskId", () => {
      service.register(1, "shell", "s1");

      expect(service.getByTaskId("task-1")).toEqual([]);
    });
  });

  describe("killByTaskId", () => {
    it("kills all processes for a given taskId", () => {
      service.register(1, "agent", "a1", undefined, "task-1");
      service.register(2, "agent", "a2", undefined, "task-1");
      service.register(3, "agent", "a3", undefined, "task-2");

      service.killByTaskId("task-1");

      expect(mockKillProcessTree).toHaveBeenCalledWith(1);
      expect(mockKillProcessTree).toHaveBeenCalledWith(2);
      expect(mockKillProcessTree).not.toHaveBeenCalledWith(3);
      expect(service.getByTaskId("task-1")).toEqual([]);
      expect(service.getByTaskId("task-2")).toHaveLength(1);
    });

    it("does nothing for unknown taskId", () => {
      service.register(1, "agent", "a1", undefined, "task-1");

      service.killByTaskId("task-999");

      expect(mockKillProcessTree).not.toHaveBeenCalled();
      expect(service.getAll()).toHaveLength(1);
    });
  });

  describe("taskId index cleanup", () => {
    it("cleans up task index on unregister", () => {
      service.register(1, "agent", "a1", undefined, "task-1");
      service.register(2, "agent", "a2", undefined, "task-1");

      service.unregister(1, "exited");

      expect(service.getByTaskId("task-1")).toHaveLength(1);
      expect(service.getByTaskId("task-1")[0].pid).toBe(2);
    });

    it("cleans up task index on kill", () => {
      service.register(1, "agent", "a1", undefined, "task-1");

      service.kill(1);

      expect(service.getByTaskId("task-1")).toEqual([]);
    });

    it("updates task index when PID is re-registered under different task", () => {
      service.register(1, "agent", "a1", undefined, "task-1");
      service.register(1, "agent", "a1-new", undefined, "task-2");

      expect(service.getByTaskId("task-1")).toEqual([]);
      expect(service.getByTaskId("task-2")).toHaveLength(1);
    });

    it("clears task index on killAll", () => {
      service.register(1, "agent", "a1", undefined, "task-1");
      service.register(2, "agent", "a2", undefined, "task-2");

      service.killAll();

      expect(service.getByTaskId("task-1")).toEqual([]);
      expect(service.getByTaskId("task-2")).toEqual([]);
    });
  });

  describe("killAll", () => {
    it("kills all tracked processes and clears the map", () => {
      service.register(1, "shell", "s1");
      service.register(2, "agent", "a1");
      service.register(3, "child", "c1");

      service.killAll();

      expect(mockKillProcessTree).toHaveBeenCalledWith(1);
      expect(mockKillProcessTree).toHaveBeenCalledWith(2);
      expect(mockKillProcessTree).toHaveBeenCalledWith(3);
      expect(service.getAll()).toHaveLength(0);
    });

    it("does nothing when no processes are tracked", () => {
      service.killAll();

      expect(mockKillProcessTree).not.toHaveBeenCalled();
    });
  });
});
