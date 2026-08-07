import http from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentPluginHttpProxyService } from "./http-proxy";

const logger = {
  scope: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
};

interface ProxyRequestOptions {
  body?: Buffer;
  headers?: Record<string, string>;
  method?: string;
}

function requestProxy(
  url: string,
  options: ProxyRequestOptions = {},
): Promise<{ status: number | undefined; body: string }> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      url,
      {
        method: options.method ?? "POST",
        headers: {
          accept: "application/json, text/event-stream",
          ...options.headers,
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            body: Buffer.concat(chunks).toString("utf8"),
          }),
        );
      },
    );
    request.on("error", reject);
    request.end(options.body);
  });
}

function registration(
  overrides: Partial<
    Parameters<AgentPluginHttpProxyService["register"]>[0]
  > = {},
): Parameters<AgentPluginHttpProxyService["register"]>[0] {
  return {
    id: "run-1:server",
    runId: "run-1",
    installationId: "installation-1",
    url: "https://origin.example.com/mcp",
    headers: { "X-Plugin": "example" },
    ...overrides,
  };
}

function okResponse(): Response {
  return new Response("ok", {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("AgentPluginHttpProxyService", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([
    ["cross-origin", "https://other.example.com/mcp"],
    ["HTTPS downgrade", "http://origin.example.com/mcp"],
    ["loopback", "https://127.0.0.1/mcp"],
    ["private IPv4", "https://10.0.0.1/mcp"],
    ["link-local", "https://169.254.1.1/mcp"],
    ["userinfo", "https://user:pass@origin.example.com/mcp"],
    ["fragment", "https://origin.example.com/mcp#fragment"],
  ])(
    "blocks a %s redirect before another request",
    async (_label, location) => {
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(
        new Response(null, {
          status: 307,
          headers: { location },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      const proxy = new AgentPluginHttpProxyService(logger as never);

      try {
        const proxyUrl = await proxy.register(registration());

        expect((await requestProxy(proxyUrl)).status).toBe(502);
        expect(fetchMock).toHaveBeenCalledTimes(1);
      } finally {
        await proxy.stop();
      }
    },
  );

  it("follows same-origin redirects without exposing configured headers elsewhere", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(null, {
          status: 307,
          headers: { location: "/next" },
        }),
      )
      .mockResolvedValueOnce(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(
        registration({ headers: { Authorization: "visible-value" } }),
      );

      expect((await requestProxy(proxyUrl)).status).toBe(200);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(new URL(fetchMock.mock.calls[1][0] as URL).toString()).toBe(
        "https://origin.example.com/next",
      );
      const redirectedHeaders = new Headers(
        fetchMock.mock.calls[1][1]?.headers,
      );
      expect(redirectedHeaders.get("authorization")).toBe("visible-value");
    } finally {
      await proxy.stop();
    }
  });

  it("detects redirect loops and enforces the hop limit", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location: "/mcp" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());

      expect((await requestProxy(proxyUrl)).status).toBe(502);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      await proxy.stop();
    }
  });

  it("uses an unguessable route and rejects browser-origin requests", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());
      const token = new URL(proxyUrl).pathname.slice(1);

      expect(token).not.toContain("run-1");
      expect(token.length).toBeGreaterThanOrEqual(40);
      expect(
        (
          await requestProxy(proxyUrl, {
            headers: { Origin: "https://attacker.example.com" },
          })
        ).status,
      ).toBe(403);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      await proxy.stop();
    }
  });

  it("rejects oversized request bodies before fetching upstream", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());
      const result = await requestProxy(proxyUrl, {
        body: Buffer.alloc(2 * 1024 * 1024 + 1),
      });

      expect(result.status).toBe(413);
      expect(result.body).toContain("too large");
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      await proxy.stop();
    }
  });

  it("aborts body collection when a run is unregistered", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());
      const result = new Promise<number | undefined>((resolve, reject) => {
        const request = http.request(
          proxyUrl,
          { method: "POST" },
          (response) => {
            response.resume();
            response.on("end", () => resolve(response.statusCode));
          },
        );
        request.on("error", reject);
        request.write("partial");
        setImmediate(() => proxy.unregisterRun("run-1"));
      });

      expect(await result).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      await proxy.stop();
    }
  });

  it("does not return an upstream response after the target is removed", async () => {
    let resolveFetch: ((response: Response) => void) | undefined;
    let notifyFetchStarted: (() => void) | undefined;
    const fetchStarted = new Promise<void>((resolve) => {
      notifyFetchStarted = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
          notifyFetchStarted?.();
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());
      const result = requestProxy(proxyUrl);
      await fetchStarted;
      proxy.unregisterInstallation("installation-1");
      resolveFetch?.(okResponse());

      expect((await result).status).toBe(404);
    } finally {
      await proxy.stop();
    }
  });

  it("revokes active routes by installation", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register(registration());
      proxy.unregisterInstallation("installation-1");

      expect((await requestProxy(proxyUrl)).status).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      await proxy.stop();
    }
  });
});
