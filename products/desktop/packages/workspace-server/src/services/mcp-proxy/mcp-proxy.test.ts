import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { McpProxyService } from "./mcp-proxy";
import type { McpProxyAuth } from "./ports";

type AuthServiceMock = {
  authenticatedFetch: ReturnType<typeof vi.fn>;
  refreshAccessToken: ReturnType<typeof vi.fn>;
  getValidAccessToken: ReturnType<typeof vi.fn>;
};

function createAuthServiceMock(): AuthServiceMock {
  return {
    authenticatedFetch: vi.fn(),
    refreshAccessToken: vi.fn().mockResolvedValue({
      accessToken: "refreshed-token",
      apiHost: "https://app.posthog.com",
    }),
    getValidAccessToken: vi.fn().mockResolvedValue({
      accessToken: "access-token",
      apiHost: "https://app.posthog.com",
    }),
  };
}

describe("McpProxyService", () => {
  let authServiceMock: AuthServiceMock;
  let service: McpProxyService;

  beforeEach(() => {
    authServiceMock = createAuthServiceMock();
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
    service = new McpProxyService(
      authServiceMock as unknown as McpProxyAuth,
      loggerMock,
    );
  });

  afterEach(async () => {
    await service.stop();
    vi.restoreAllMocks();
  });

  describe("lifecycle", () => {
    it("starts on a loopback port and returns a URL for register()", async () => {
      await service.start();
      const url = service.register("alpha", "https://upstream.example/path");
      expect(url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/alpha$/);
    });

    it("throws from register() before start()", () => {
      expect(() =>
        service.register("alpha", "https://upstream.example"),
      ).toThrowError(/not started/);
    });

    it("handles concurrent start() calls without races", async () => {
      await Promise.all([service.start(), service.start(), service.start()]);
      const url = service.register("alpha", "https://upstream.example");
      expect(url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/alpha$/);
    });

    it("stop() closes the server and clears registered targets", async () => {
      await service.start();
      service.register("alpha", "https://upstream.example");
      await service.stop();
      expect(() =>
        service.register("alpha", "https://upstream.example"),
      ).toThrowError(/not started/);
    });
  });

  describe("request forwarding", () => {
    it("returns 404 for unknown targets", async () => {
      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");
      const unknownUrl = proxyUrl.replace("/alpha", "/bravo");

      const res = await fetch(unknownUrl);

      expect(res.status).toBe(404);
      expect(await res.text()).toBe("Unknown target");
      expect(authServiceMock.authenticatedFetch).not.toHaveBeenCalled();
    });

    it("forwards GET requests and returns the upstream body and status", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      const res = await fetch(proxyUrl);

      expect(res.status).toBe(200);
      expect(await res.text()).toBe('{"ok":true}');
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
      const [url] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(url).toBe("https://upstream.example");
    });

    it("passes a connection-lifetime signal so authenticatedFetch's default timeout does not apply", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      await fetch(proxyUrl);

      const [, options] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(options.signal).toBeInstanceOf(AbortSignal);
      expect(options.signal.aborted).toBe(false);
    });

    it("forwards POST body bytes to the upstream URL", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      await fetch(proxyUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: '{"hello":"world"}',
      });

      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
      const [, options] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(options.method).toBe("POST");
      expect(Buffer.from(options.body).toString("utf8")).toBe(
        '{"hello":"world"}',
      );

      const forwardedHeaderKeys = Object.keys(options.headers).map((key) =>
        key.toLowerCase(),
      );
      expect(forwardedHeaderKeys).not.toContain("content-length");
      expect(forwardedHeaderKeys).not.toContain("transfer-encoding");
    });

    it("strips Authorization and Host headers before forwarding", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      await fetch(proxyUrl, {
        headers: {
          Authorization: "Bearer leaked",
          "X-Custom": "keep-me",
        },
      });

      const [, options] = authServiceMock.authenticatedFetch.mock.calls[0];
      const forwardedHeaderKeys = Object.keys(options.headers).map((k) =>
        k.toLowerCase(),
      );
      expect(forwardedHeaderKeys).not.toContain("authorization");
      expect(forwardedHeaderKeys).not.toContain("host");
      expect(forwardedHeaderKeys).not.toContain("connection");
      expect(options.headers["x-custom"]).toBe("keep-me");
    });

    it("joins path suffix without producing a double slash for trailing-slash targets", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response("{}", {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      service.register("alpha", "https://upstream.example/inst-2/");
      const port = new URL(
        service.register("alpha", "https://upstream.example/inst-2/"),
      ).port;

      await fetch(`http://127.0.0.1:${port}/alpha/tools/list`);

      const [url] = authServiceMock.authenticatedFetch.mock.calls.at(-1) ?? [];
      expect(url).toBe("https://upstream.example/inst-2/tools/list");
    });

    it("preserves the incoming query string on the upstream URL", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response("{}", {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      await fetch(`${proxyUrl}?token=abc&foo=bar`);

      const [url] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(url).toBe("https://upstream.example?token=abc&foo=bar");
    });
  });

  describe("auth error retry", () => {
    it("refreshes the token and retries once when the body contains authentication_failed", async () => {
      authServiceMock.authenticatedFetch
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ error: { code: "authentication_failed" } }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        )
        .mockResolvedValueOnce(
          new Response('{"ok":true}', {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      const res = await fetch(proxyUrl, { method: "POST", body: "payload" });

      expect(res.status).toBe(200);
      expect(await res.text()).toBe('{"ok":true}');
      expect(authServiceMock.refreshAccessToken).toHaveBeenCalledTimes(1);
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(2);
    });

    it("does not retry when the body looks healthy", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      await fetch(proxyUrl);

      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("SSE streaming", () => {
    it("streams event-stream responses through to the client", async () => {
      const sseBody = "data: one\n\ndata: two\n\n";
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response(sseBody, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      );

      await service.start();
      const proxyUrl = service.register("alpha", "https://upstream.example");

      const res = await fetch(proxyUrl);

      expect(res.headers.get("content-type")).toContain("text/event-stream");
      expect(await res.text()).toBe(sseBody);
      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
    });
  });
});
