import { beforeEach, describe, expect, it, vi } from "vitest";

const listenMock = vi.hoisted(() => vi.fn());
const serverHandlers = vi.hoisted(
  () => new Map<string, (arg: unknown) => void>(),
);

vi.mock("node:http", () => {
  const createServer = vi.fn(() => ({
    listen: listenMock,
    close: vi.fn(),
    on: vi.fn((event: string, handler: (arg: unknown) => void) => {
      serverHandlers.set(event, handler);
    }),
  }));
  return { createServer, default: { createServer } };
});

import { OAuthCallbackServer } from "./oauth-callback";

describe("OAuthCallbackServer.waitForCode", () => {
  beforeEach(() => {
    serverHandlers.clear();
    listenMock.mockReset();
  });

  it("binds the callback server to the loopback interface only", async () => {
    listenMock.mockImplementation(
      (_port: number, _host: string, cb: () => void) => cb(),
    );
    const controller = new AbortController();
    const onListening = vi.fn();

    const promise = new OAuthCallbackServer().waitForCode({
      port: 12345,
      timeoutMs: 1000,
      signal: controller.signal,
      onListening,
    });
    // The flow never resolves in this test; swallow the cancel rejection.
    promise.catch(() => {});

    expect(listenMock).toHaveBeenCalledWith(
      12345,
      "127.0.0.1",
      expect.any(Function),
    );
    expect(onListening).toHaveBeenCalledTimes(1);

    controller.abort();
    await expect(promise).rejects.toThrow("OAuth flow cancelled");
  });

  it("names the other app when the callback port is taken", async () => {
    listenMock.mockImplementation(() => {
      const error: NodeJS.ErrnoException = new Error(
        "listen EADDRINUSE: address already in use 127.0.0.1:8237",
      );
      error.code = "EADDRINUSE";
      serverHandlers.get("error")?.(error);
    });

    await expect(
      new OAuthCallbackServer().waitForCode({ port: 8237, timeoutMs: 1000 }),
    ).rejects.toThrow(
      "Another PostHog app is signing in on port 8237. Finish that sign-in, then try again.",
    );
  });
});
