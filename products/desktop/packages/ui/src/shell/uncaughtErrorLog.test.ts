import { afterEach, describe, expect, it, vi } from "vitest";

const error = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({ error, warn: vi.fn(), info: vi.fn(), debug: vi.fn() }),
  },
}));

import { installUncaughtErrorLogging } from "./uncaughtErrorLog";

describe("installUncaughtErrorLogging", () => {
  afterEach(() => error.mockClear());

  it("mirrors uncaught errors into the host log, capped per minute", () => {
    const uninstall = installUncaughtErrorLogging();
    try {
      for (let i = 0; i < 25; i++) {
        window.dispatchEvent(
          new ErrorEvent("error", {
            message: `boom ${i}`,
            filename: "renderer.js",
            lineno: 1,
            colno: 2,
            error: new Error(`boom ${i}`),
          }),
        );
      }
      expect(error).toHaveBeenCalledTimes(20);
      expect(error).toHaveBeenCalledWith(
        "Uncaught renderer error",
        expect.objectContaining({
          message: "boom 0",
          source: "renderer.js:1:2",
        }),
      );
    } finally {
      uninstall();
    }
  });

  it("stops listening once uninstalled", () => {
    installUncaughtErrorLogging()();
    window.dispatchEvent(new ErrorEvent("error", { message: "late" }));
    expect(error).not.toHaveBeenCalled();
  });
});
