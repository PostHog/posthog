import { describe, expect, it, vi } from "vitest";
import {
  findMatchingProcessTargets,
  findProcessTree,
  killUnixProcessTrees,
} from "./process-utils";

const startedAt = "Sat Jul 25 00:00:00 2026";

describe("findProcessTree", () => {
  it("returns descendants deepest-first across nested process groups", () => {
    const result = findProcessTree(10, [
      { pid: 1, ppid: 0, pgid: 1, startedAt },
      { pid: 10, ppid: 1, pgid: 10, startedAt },
      { pid: 11, ppid: 10, pgid: 10, startedAt },
      { pid: 12, ppid: 11, pgid: 12, startedAt },
      { pid: 13, ppid: 12, pgid: 12, startedAt },
      { pid: 20, ppid: 1, pgid: 20, startedAt },
    ]);

    expect(result).toEqual([
      { pid: 13, ppid: 12, pgid: 12, startedAt },
      { pid: 12, ppid: 11, pgid: 12, startedAt },
      { pid: 11, ppid: 10, pgid: 10, startedAt },
      { pid: 10, ppid: 1, pgid: 10, startedAt },
    ]);
  });

  it("returns no unrelated processes when the root has exited", () => {
    expect(
      findProcessTree(10, [{ pid: 20, ppid: 1, pgid: 20, startedAt }]),
    ).toEqual([]);
  });
});

describe("findMatchingProcessTargets", () => {
  it("excludes reused process and group ids", () => {
    const original = [
      { pid: 10, ppid: 1, pgid: 10, startedAt },
      { pid: 11, ppid: 10, pgid: 11, startedAt },
    ];
    const current = [
      { pid: 10, ppid: 1, pgid: 10, startedAt: "later" },
      { pid: 11, ppid: 1, pgid: 11, startedAt: "later" },
    ];

    expect(findMatchingProcessTargets(original, current, undefined)).toEqual(
      [],
    );
  });

  it("targets surviving descendants after they are reparented", () => {
    const original = [
      { pid: 11, ppid: 10, pgid: 11, startedAt },
      { pid: 10, ppid: 1, pgid: 10, startedAt },
    ];
    const current = [{ pid: 11, ppid: 1, pgid: 11, startedAt }];

    expect(findMatchingProcessTargets(original, current, undefined)).toEqual([
      -11, 11,
    ]);
  });
});

describe("killUnixProcessTrees", () => {
  it("revalidates identities before the delayed kill", () => {
    const original = [
      { pid: 1, ppid: 0, pgid: 1, startedAt },
      { pid: 10, ppid: 1, pgid: 10, startedAt },
      { pid: 11, ppid: 10, pgid: 11, startedAt },
    ];
    const current = [
      { pid: 10, ppid: 1, pgid: 10, startedAt: "reused" },
      { pid: 11, ppid: 1, pgid: 11, startedAt },
    ];
    const signal = vi.fn();
    let delayed: (() => void) | undefined;

    killUnixProcessTrees([10], original, 1, {
      currentProcesses: () => current,
      signal,
      schedule: (callback) => {
        delayed = callback;
      },
    });
    delayed?.();

    expect(signal.mock.calls).toEqual([
      [[-10, -11, 10, 11], "SIGTERM"],
      [[-11, 11], "SIGKILL"],
    ]);
  });

  it("falls back to the raw group when the root identity is unavailable", () => {
    const signal = vi.fn();
    const schedule = vi.fn();

    killUnixProcessTrees([10], [{ pid: 20, ppid: 1, pgid: 20, startedAt }], 1, {
      currentProcesses: () => [],
      signal,
      schedule,
    });

    expect(signal).toHaveBeenCalledWith([-10, 10], "SIGTERM");
    expect(schedule).not.toHaveBeenCalled();
  });

  it("falls back for missing roots in a mixed batch", () => {
    const signal = vi.fn();

    killUnixProcessTrees(
      [10, 20],
      [{ pid: 10, ppid: 1, pgid: 10, startedAt }],
      1,
      {
        currentProcesses: () => [],
        signal,
        schedule: vi.fn(),
      },
    );

    expect(signal).toHaveBeenCalledWith([-20, 20, -10, 10], "SIGTERM");
  });
});
