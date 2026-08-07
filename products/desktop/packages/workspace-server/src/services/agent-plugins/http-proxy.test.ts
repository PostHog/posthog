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

function requestProxy(url: string): Promise<number | undefined> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      url,
      {
        method: "POST",
        headers: { accept: "application/json, text/event-stream" },
      },
      (response) => {
        response.resume();
        response.on("end", () => resolve(response.statusCode));
      },
    );
    request.on("error", reject);
    request.end();
  });
}

describe("AgentPluginHttpProxyService", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("removes configured headers before following a cross-origin redirect", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(null, {
          status: 307,
          headers: { location: "https://other.example.com/mcp" },
        }),
      )
      .mockResolvedValueOnce(
        new Response("ok", {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const proxy = new AgentPluginHttpProxyService(logger as never);

    try {
      const proxyUrl = await proxy.register({
        id: "run-1:server",
        runId: "run-1",
        url: "https://origin.example.com/mcp",
        headers: {
          Authorization: "Bearer visible-package-value",
          "X-Plugin": "example",
          Accept: "configured-value",
        },
      });

      expect(await requestProxy(proxyUrl)).toBe(200);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      const firstHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
      expect(firstHeaders.get("authorization")).toBe(
        "Bearer visible-package-value",
      );
      expect(firstHeaders.get("x-plugin")).toBe("example");
      expect(firstHeaders.get("accept")).toBe(
        "application/json, text/event-stream",
      );

      const redirectedHeaders = new Headers(
        fetchMock.mock.calls[1][1]?.headers,
      );
      expect(redirectedHeaders.has("authorization")).toBe(false);
      expect(redirectedHeaders.has("x-plugin")).toBe(false);
      expect(redirectedHeaders.get("accept")).toBe(
        "application/json, text/event-stream",
      );
    } finally {
      await proxy.stop();
    }
  });
});
