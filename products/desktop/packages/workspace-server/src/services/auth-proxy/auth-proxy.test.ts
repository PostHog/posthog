import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProxyService } from "./auth-proxy";
import type { AuthProxyAuth } from "./ports";

type AuthMock = {
  authenticatedFetch: ReturnType<typeof vi.fn>;
};

describe("AuthProxyService", () => {
  let authMock: AuthMock;
  let service: AuthProxyService;

  beforeEach(() => {
    authMock = { authenticatedFetch: vi.fn() };
    const loggerMock: RootLogger = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      scope: () => ({
        debug: vi.fn(),
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
      }),
    };
    service = new AuthProxyService(
      authMock as unknown as AuthProxyAuth,
      loggerMock,
    );
  });

  afterEach(async () => {
    await service.stop();
    vi.restoreAllMocks();
  });

  it("forwards requests and returns the upstream body and status", async () => {
    authMock.authenticatedFetch.mockResolvedValue(
      new Response('{"ok":true}', {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const proxyUrl = await service.start("https://gateway.example");
    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(200);
    expect(await res.text()).toBe('{"ok":true}');
    const [url] = authMock.authenticatedFetch.mock.calls[0];
    expect(url).toBe("https://gateway.example/v1/messages");
  });

  it("rejects requests that do not include the generated access token", async () => {
    const proxyUrl = await service.start("https://gateway.example");
    const proxyOrigin = new URL(proxyUrl).origin;

    const missingToken = await fetch(`${proxyOrigin}/v1/messages`);
    const invalidToken = await fetch(`${proxyOrigin}/invalid/v1/messages`);

    expect(missingToken.status).toBe(401);
    expect(invalidToken.status).toBe(401);
    expect(authMock.authenticatedFetch).not.toHaveBeenCalled();
  });

  it("strips client body framing headers before forwarding", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example");
    await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    const forwardedHeaderKeys = Object.keys(
      options.headers as Record<string, string>,
    ).map((key) => key.toLowerCase());

    expect(forwardedHeaderKeys).not.toContain("content-length");
    expect(forwardedHeaderKeys).not.toContain("transfer-encoding");
    expect(options.headers["content-type"]).toBe("application/json");
  });

  it("passes a connection-lifetime signal so authenticatedFetch's default timeout does not apply", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example");
    await fetch(`${proxyUrl}/v1/messages`, { method: "POST", body: "{}" });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.signal.aborted).toBe(false);
  });

  it("aborts the upstream fetch when the client disconnects mid-stream", async () => {
    let upstreamSignal: AbortSignal | undefined;
    authMock.authenticatedFetch.mockImplementation(
      async (_url: string, options: RequestInit) => {
        upstreamSignal = options.signal ?? undefined;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode("data: one\n\n"));
            // Never closes — simulates an in-flight LLM stream.
          },
        });
        return new Response(stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      },
    );

    const proxyUrl = await service.start("https://gateway.example");
    const clientAbort = new AbortController();
    const res = await fetch(`${proxyUrl}/v1/messages`, {
      signal: clientAbort.signal,
    });
    const reader = res.body?.getReader();
    await reader?.read();

    expect(upstreamSignal?.aborted).toBe(false);
    clientAbort.abort();

    await vi.waitFor(() => {
      expect(upstreamSignal?.aborted).toBe(true);
    });
  });

  it("streams the upstream body through to the client", async () => {
    authMock.authenticatedFetch.mockResolvedValue(
      new Response("data: one\n\ndata: two\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );

    const proxyUrl = await service.start("https://gateway.example");
    const res = await fetch(`${proxyUrl}/v1/messages`);

    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(await res.text()).toBe("data: one\n\ndata: two\n\n");
  });
});
