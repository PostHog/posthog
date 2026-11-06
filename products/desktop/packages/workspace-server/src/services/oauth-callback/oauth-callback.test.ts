import { describe, expect, it, vi } from "vitest";

const listenMock = vi.hoisted(() => vi.fn());

vi.mock("node:http", () => {
  const createServer = vi.fn(() => ({
    listen: listenMock,
    close: vi.fn(),
    on: vi.fn(),
  }));
  return { createServer, default: { createServer } };
});

import { OAuthCallbackServer } from "./oauth-callback";

describe("OAuthCallbackServer.waitForCode", () => {
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
});
