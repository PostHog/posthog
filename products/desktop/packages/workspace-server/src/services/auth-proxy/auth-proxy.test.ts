import http from "node:http";
import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProxyService, MAX_BODY_BYTES, PROXY_TIMEOUTS } from "./auth-proxy";
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

  it("forwards trusted headers instead of client-supplied values", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example", {
      "X-PostHog-Project-Id": "1",
    });
    await fetch(`${proxyUrl}/v1/messages`, {
      headers: { "X-PostHog-Project-Id": "999" },
    });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    const headers = new Headers(options.headers);
    expect(headers.get("X-PostHog-Project-Id")).toBe("1");
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

describe("AuthProxyService legacy hardening", () => {
  let authFetch: ReturnType<typeof vi.fn>;
  let logs: unknown[][];
  let service: AuthProxyService;

  beforeEach(() => {
    authFetch = vi.fn();
    logs = [];
    const record =
      (level: string) =>
      (...args: unknown[]) =>
        logs.push([level, ...args]);
    const scoped = {
      debug: record("debug"),
      info: record("info"),
      warn: record("warn"),
      error: record("error"),
    };
    const logger = { ...scoped, scope: () => scoped } as unknown as RootLogger;
    service = new AuthProxyService(
      { authenticatedFetch: authFetch } as AuthProxyAuth,
      logger,
    );
  });

  afterEach(async () => {
    await service.stop();
  });

  it("strips inbound credentials and cookies and refuses redirects", async () => {
    authFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await service.start("https://gateway.example");

    await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      headers: {
        authorization: "Bearer posthog-code-auth-proxy",
        "x-api-key": "posthog-code-auth-proxy",
        cookie: "session=abc",
      },
      body: "{}",
    });

    const [, init] = authFetch.mock.calls[0];
    expect(init.redirect).toBe("manual");
    expect(init.headers).not.toHaveProperty("authorization");
    expect(init.headers).not.toHaveProperty("x-api-key");
    expect(init.headers).not.toHaveProperty("cookie");
  });

  it("strips cookies and auth challenges from the response", async () => {
    authFetch.mockResolvedValue(
      new Response("ok", {
        headers: {
          "set-cookie": "a=b",
          "www-authenticate": "Bearer",
          "x-posthog-trace-id": "trace",
        },
      }),
    );
    const proxyUrl = await service.start("https://gateway.example");

    const res = await fetch(`${proxyUrl}/v1/messages`);

    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("www-authenticate")).toBeNull();
    expect(res.headers.get("x-posthog-trace-id")).toBe("trace");
  });

  function hopRequest(
    url: string,
    headers: http.OutgoingHttpHeaders,
  ): Promise<http.IncomingMessage> {
    return new Promise((resolve, reject) => {
      const req = http.request(url, { headers, agent: false }, (res) => {
        res.resume();
        res.on("end", () => resolve(res));
      });
      req.on("error", reject);
      req.end();
    });
  }

  it("strips hop-by-hop request headers and any the Connection value names", async () => {
    authFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await service.start("https://gateway.example");

    await hopRequest(`${proxyUrl}/v1/models`, {
      connection: "close, x-hop",
      "keep-alive": "timeout=5",
      "proxy-connection": "keep-alive",
      te: "trailers",
      upgrade: "websocket",
      "x-hop": "1",
      "x-kept": "1",
    });

    const headers = Object.keys(authFetch.mock.calls[0][1].headers);
    for (const name of [
      "connection",
      "keep-alive",
      "proxy-connection",
      "te",
      "upgrade",
      "x-hop",
    ]) {
      expect(headers).not.toContain(name);
    }
    expect(headers).toContain("x-kept");
  });

  it("strips hop-by-hop response headers and any the Connection value names", async () => {
    authFetch.mockResolvedValue(
      new Response("ok", {
        headers: {
          connection: "x-hop",
          "keep-alive": "timeout=999",
          "proxy-connection": "keep-alive",
          trailer: "x-sum",
          upgrade: "websocket",
          "x-hop": "1",
          "x-kept": "1",
        },
      }),
    );
    const proxyUrl = await service.start("https://gateway.example");

    const res = await hopRequest(`${proxyUrl}/v1/models`, {});

    expect(res.headers["keep-alive"]).toBeUndefined();
    for (const name of ["proxy-connection", "trailer", "upgrade", "x-hop"]) {
      expect(res.headers[name]).toBeUndefined();
    }
    expect(res.headers["x-kept"]).toBe("1");
  });

  it("turns an upstream redirect into a 502", async () => {
    authFetch.mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { location: "https://evil.example" },
      }),
    );
    const proxyUrl = await service.start("https://gateway.example");

    const res = await fetch(`${proxyUrl}/v1/messages`, { redirect: "manual" });

    expect(res.status).toBe(502);
    expect(res.headers.get("location")).toBeNull();
  });

  it("refuses a body over the cap with a size error the classifier knows", async () => {
    const proxyUrl = await service.start("https://gateway.example");

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: Buffer.alloc(MAX_BODY_BYTES + 1, 97),
    });

    expect(res.status).toBe(413);
    expect(await res.text()).toContain("request body too large");
    expect(authFetch).not.toHaveBeenCalled();
  });

  it("never logs the path token or the upstream query string", async () => {
    authFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await service.start("https://gateway.example");
    const token = new URL(proxyUrl).pathname.slice(1);
    const origin = new URL(proxyUrl).origin;

    await fetch(`${proxyUrl}/v1/messages?secret=q`);
    const traversal = await rawRequest(`${origin}/${token}/..%2f..%2fx`);
    expect(traversal).toBe(403);
    authFetch.mockRejectedValueOnce(new Error("boom"));
    await fetch(`${proxyUrl}/v1/messages?secret=q`);

    const text = JSON.stringify(logs);
    expect(logs.length).toBeGreaterThan(0);
    expect(text).not.toContain(token);
    expect(text).not.toContain("secret=q");
  });

  describe("timeouts", () => {
    const saved = { ...PROXY_TIMEOUTS };
    afterEach(() => Object.assign(PROXY_TIMEOUTS, saved));

    it("answers 408 when the request body stalls", async () => {
      PROXY_TIMEOUTS.bodyMs = 50;
      const proxyUrl = await service.start("https://gateway.example");

      const status = await new Promise<number>((resolve, reject) => {
        const req = http.request(`${proxyUrl}/v1/messages`, {
          method: "POST",
          headers: { "content-length": "100" },
        });
        req.on("response", (res) => {
          res.resume();
          resolve(res.statusCode ?? 0);
        });
        req.on("error", reject);
        req.write("partial");
      });

      expect(status).toBe(408);
      expect(authFetch).not.toHaveBeenCalled();
    });

    it("keeps streaming past the headers timeout once headers arrive", async () => {
      PROXY_TIMEOUTS.headersMs = 50;
      authFetch.mockImplementation(async (_url: string, init: RequestInit) => {
        const body = new ReadableStream<Uint8Array>({
          async start(controller) {
            init.signal?.addEventListener("abort", () =>
              controller.error(new DOMException("aborted", "AbortError")),
            );
            controller.enqueue(new TextEncoder().encode("a"));
            await new Promise((resolve) => setTimeout(resolve, 150));
            controller.enqueue(new TextEncoder().encode("b"));
            controller.close();
          },
        });
        return new Response(body);
      });
      const proxyUrl = await service.start("https://gateway.example");

      const res = await fetch(`${proxyUrl}/v1/messages`);

      expect(await res.text()).toBe("ab");
    });

    it("answers 504 and logs a warning when the upstream sends no headers", async () => {
      PROXY_TIMEOUTS.headersMs = 50;
      authFetch.mockImplementation(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
          }),
      );
      const proxyUrl = await service.start("https://gateway.example");

      const res = await fetch(`${proxyUrl}/v1/messages`);

      expect(res.status).toBe(504);
      expect(
        logs.some(
          ([level, message]) =>
            level === "warn" &&
            message === "Auth proxy upstream sent no response headers in time",
        ),
      ).toBe(true);
    });
  });
});

function rawRequest(url: string): Promise<number> {
  const parsed = new URL(url);
  return new Promise((resolve, reject) => {
    const req = http.request({
      host: parsed.hostname,
      port: parsed.port,
      path: url.slice(parsed.origin.length),
    });
    req.on("response", (res) => {
      res.resume();
      resolve(res.statusCode ?? 0);
    });
    req.on("error", reject);
    req.end();
  });
}
