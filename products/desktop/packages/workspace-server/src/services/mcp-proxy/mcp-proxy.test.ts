import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MCP_PROXY_TOKEN_HEADER, McpProxyService } from "./mcp-proxy";
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

const okJson = () =>
  new Response('{"ok":true}', {
    status: 200,
    headers: { "content-type": "application/json" },
  });

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

  /** Fetch with the secret register() handed out, like a real transport. */
  const authedFetch = (url: string, token: string, init?: RequestInit) =>
    fetch(url, {
      ...init,
      headers: { ...init?.headers, [MCP_PROXY_TOKEN_HEADER]: token },
    });

  describe("lifecycle", () => {
    it("starts on a loopback port and returns a URL and a secret for register()", async () => {
      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example/path",
      );
      expect(url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/alpha$/);
      expect(token).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      );
    });

    it("throws from register() before start()", () => {
      expect(() =>
        service.register("alpha", "https://upstream.example"),
      ).toThrowError(/not started/);
    });

    it("handles concurrent start() calls without races", async () => {
      await Promise.all([service.start(), service.start(), service.start()]);
      const { url } = service.register("alpha", "https://upstream.example");
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

  describe("secret enforcement", () => {
    it("rejects a request without the secret and never reaches the upstream", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url } = service.register("alpha", "https://upstream.example");

      const res = await fetch(url);

      expect(res.status).toBe(401);
      expect(authServiceMock.authenticatedFetch).not.toHaveBeenCalled();
    });

    it("rejects a request with the wrong secret, even one from another target", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const alpha = service.register("alpha", "https://upstream.example");
      const bravo = service.register("bravo", "https://upstream.example");

      const res = await authedFetch(alpha.url, bravo.token);

      expect(res.status).toBe(401);
      expect(authServiceMock.authenticatedFetch).not.toHaveBeenCalled();
    });

    it("keeps the secret when the target is re-registered with the same upstream", async () => {
      // buildMcpServers runs on every session start and re-registers the same
      // IDs, while live transports keep sending the token they were built with.
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const first = service.register("alpha", "https://upstream.example");
      const second = service.register("alpha", "https://upstream.example");

      expect(second.token).toBe(first.token);
      const res = await authedFetch(first.url, first.token);
      expect(res.status).toBe(200);
    });

    it("rotates the secret when the upstream changes", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const first = service.register("alpha", "https://upstream.example");
      const second = service.register("alpha", "https://other.example");

      const rejected = await authedFetch(first.url, first.token);
      const accepted = await authedFetch(second.url, second.token);

      expect(rejected.status).toBe(401);
      expect(accepted.status).toBe(200);
    });

    it("rotates the secret when the identity changes, even on the same upstream", async () => {
      // The forwarded request carries the current user's token, so a secret
      // issued under one account or project must not outlive a switch.
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const first = service.register("posthog", "https://mcp.example/mcp", {
        identity: "https://app.posthog.com#42",
      });
      const second = service.register("posthog", "https://mcp.example/mcp", {
        identity: "https://app.posthog.com#43",
      });

      const rejected = await authedFetch(first.url, first.token);
      const accepted = await authedFetch(second.url, second.token);

      expect(rejected.status).toBe(401);
      expect(accepted.status).toBe(200);
    });

    it("answers the RFC 8414 discovery probe with 404 without a secret", async () => {
      await service.start();
      const { url } = service.register("alpha", "https://upstream.example");
      const port = new URL(url).port;

      const res = await fetch(
        `http://127.0.0.1:${port}/.well-known/oauth-authorization-server`,
      );

      expect(res.status).toBe(404);
      expect(authServiceMock.authenticatedFetch).not.toHaveBeenCalled();
    });
  });

  describe("request forwarding", () => {
    it("returns 404 for unknown targets", async () => {
      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );
      const unknownUrl = url.replace("/alpha", "/bravo");

      const res = await fetch(unknownUrl, {
        headers: { [MCP_PROXY_TOKEN_HEADER]: token },
      });

      expect(res.status).toBe(404);
      expect(await res.text()).toBe("Unknown target");
      expect(authServiceMock.authenticatedFetch).not.toHaveBeenCalled();
    });

    it("forwards GET requests and returns the upstream body and status", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      const res = await authedFetch(url, token);

      expect(res.status).toBe(200);
      expect(await res.text()).toBe('{"ok":true}');
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
      const [fetchedUrl] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(fetchedUrl).toBe("https://upstream.example");
    });

    it("passes a connection-lifetime signal so authenticatedFetch's default timeout does not apply", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      await authedFetch(url, token);

      const [, options] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(options.signal).toBeInstanceOf(AbortSignal);
      expect(options.signal.aborted).toBe(false);
    });

    it("forwards POST body bytes to the upstream URL", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      await authedFetch(url, token, {
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

    it("strips Authorization, Host, and the proxy secret before forwarding", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      await authedFetch(url, token, {
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
      expect(forwardedHeaderKeys).not.toContain(MCP_PROXY_TOKEN_HEADER);
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
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example/inst-2/",
      );

      await authedFetch(`${url}/tools/list`, token);

      const [fetchedUrl] =
        authServiceMock.authenticatedFetch.mock.calls.at(-1) ?? [];
      expect(fetchedUrl).toBe("https://upstream.example/inst-2/tools/list");
    });

    it("preserves the incoming query string on the upstream URL", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      await authedFetch(`${url}?token=abc&foo=bar`, token);

      const [fetchedUrl] = authServiceMock.authenticatedFetch.mock.calls[0];
      expect(fetchedUrl).toBe("https://upstream.example?token=abc&foo=bar");
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
        .mockResolvedValueOnce(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      const res = await authedFetch(url, token, {
        method: "POST",
        body: "payload",
      });

      expect(res.status).toBe(200);
      expect(await res.text()).toBe('{"ok":true}');
      expect(authServiceMock.refreshAccessToken).toHaveBeenCalledTimes(1);
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(2);
    });

    it("passes an installation credential failure through without refreshing", async () => {
      // The failing credential belongs to the connected vendor, not to PostHog, so a
      // PostHog token refresh cannot fix it and the retry only hides the real error.
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response(JSON.stringify({ error: "Authentication failed" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const { url, token } = service.register(
        "installation-abc",
        "https://app.posthog.com/api/environments/1/mcp_server_installations/abc/proxy/",
        { credentialOwner: "installation" },
      );

      const res = await authedFetch(url, token, {
        method: "POST",
        body: "payload",
      });

      expect(res.status).toBe(401);
      expect(await res.text()).toBe('{"error":"Authentication failed"}');
      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
    });

    it("does not refresh on a permission denial", async () => {
      // Permission denials share `type: "authentication_error"` with rejected
      // tokens; only a rejected token can be fixed by refreshing.
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response(
          JSON.stringify({
            type: "authentication_error",
            code: "permission_denied",
            detail: "You do not have permission to perform this action.",
          }),
          { status: 403, headers: { "content-type": "application/json" } },
        ),
      );

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      const res = await authedFetch(url, token, {
        method: "POST",
        body: "payload",
      });

      expect(res.status).toBe(403);
      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
    });

    it("does not refresh on a 403 with a generic auth failure body", async () => {
      // A refresh cannot add permissions, and each forced one rotates the
      // refresh token and rebuilds the whole desktop session.
      authServiceMock.authenticatedFetch.mockResolvedValue(
        new Response('{"error":"Invalid API key"}', {
          status: 403,
          headers: { "content-type": "application/json" },
        }),
      );

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      const res = await authedFetch(url, token, {
        method: "POST",
        body: "payload",
      });

      expect(res.status).toBe(403);
      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
      expect(authServiceMock.authenticatedFetch).toHaveBeenCalledTimes(1);
    });

    it("does not retry when the body looks healthy", async () => {
      authServiceMock.authenticatedFetch.mockResolvedValue(okJson());

      await service.start();
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      await authedFetch(url, token);

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
      const { url, token } = service.register(
        "alpha",
        "https://upstream.example",
      );

      const res = await authedFetch(url, token);

      expect(res.headers.get("content-type")).toContain("text/event-stream");
      expect(await res.text()).toBe(sseBody);
      expect(authServiceMock.refreshAccessToken).not.toHaveBeenCalled();
    });
  });
});
