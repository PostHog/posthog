import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockExecFileSync = vi.hoisted(() => vi.fn());
const mockPlatform = vi.hoisted(() => vi.fn(() => "darwin"));

vi.mock("node:child_process", () => ({
  execFileSync: mockExecFileSync,
}));

vi.mock("node:os", () => ({
  platform: mockPlatform,
}));

import { killProcessTree } from "./process-utils";

describe("killProcessTree", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockExecFileSync.mockReset();
    mockPlatform.mockReset();
    mockPlatform.mockReturnValue("darwin");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("signals Unix descendants before their parent", async () => {
    mockExecFileSync.mockReturnValue(
      [
        "4242 100 Thu Aug 28 04:00:00 2026",
        "5000 4242 Thu Aug 28 04:00:01 2026",
        "6000 5000 Thu Aug 28 04:00:02 2026",
        "5001 4242 Thu Aug 28 04:00:03 2026",
      ].join("\n"),
    );
    const killProcess = vi.spyOn(process, "kill").mockReturnValue(true);

    killProcessTree(4242);

    expect(killProcess.mock.calls).toEqual([
      [6000, "SIGTERM"],
      [5000, "SIGTERM"],
      [5001, "SIGTERM"],
      [4242, "SIGTERM"],
    ]);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(killProcess.mock.calls.slice(4)).toEqual([
      [6000, "SIGKILL"],
      [5000, "SIGKILL"],
      [5001, "SIGKILL"],
      [4242, "SIGKILL"],
    ]);
  });

  it("does not force-stop a reused Unix PID", async () => {
    mockExecFileSync
      .mockReturnValueOnce(
        [
          "4242 100 Thu Aug 28 04:00:00 2026",
          "5000 4242 Thu Aug 28 04:00:01 2026",
        ].join("\n"),
      )
      .mockReturnValueOnce(
        [
          "4242 100 Thu Aug 28 04:00:00 2026",
          "5000 100 Thu Aug 28 04:00:06 2026",
        ].join("\n"),
      );
    const killProcess = vi.spyOn(process, "kill").mockReturnValue(true);

    killProcessTree(4242);
    await vi.advanceTimersByTimeAsync(5_000);

    expect(killProcess.mock.calls).toEqual([
      [5000, "SIGTERM"],
      [4242, "SIGTERM"],
      [4242, "SIGKILL"],
    ]);
  });

  it("uses taskkill for the complete process tree on Windows", () => {
    mockPlatform.mockReturnValue("win32");

    killProcessTree(4242);

    expect(mockExecFileSync).toHaveBeenCalledWith(
      "taskkill",
      ["/PID", "4242", "/T", "/F"],
      { stdio: "ignore" },
    );
  });
});
