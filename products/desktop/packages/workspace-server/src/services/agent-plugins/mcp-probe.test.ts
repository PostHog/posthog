import { afterEach, describe, expect, it, vi } from "vitest";
import { probeMcpInitialize } from "./mcp-probe";

const MARKER = "x-posthog-agent-plugin-stdio-bridge";
const PROBE = "x-posthog-agent-plugin-stdio-probe";

function requestId(init?: RequestInit): string {
  return (JSON.parse(String(init?.body)) as { id: string }).id;
}

describe("Agent Plugin MCP initialize probe", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts a complete response with the matching request id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        Response.json({
          jsonrpc: "2.0",
          id: requestId(init),
          result: { protocolVersion: "2025-06-18" },
        }),
      ),
    );

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(true);
  });

  it("accepts a matching initialize response delivered as SSE", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (_url: string, init?: RequestInit) =>
          new Response(
            `event: message\ndata: ${JSON.stringify({
              jsonrpc: "2.0",
              id: requestId(init),
              result: { protocolVersion: "2025-06-18" },
            })}\n\n`,
            { headers: { "content-type": "text/event-stream" } },
          ),
      ),
    );

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(true);
  });

  it.each([
    ["mismatched request id", { jsonrpc: "2.0", id: "wrong", result: {} }],
    ["JSON-RPC error", { jsonrpc: "2.0", id: "dynamic", error: {} }],
    ["malformed response", "not json"],
  ])("rejects a %s", async (_label, payload) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        const body =
          typeof payload === "string"
            ? payload
            : JSON.stringify({
                ...payload,
                ...(payload.id === "dynamic" ? { id: requestId(init) } : {}),
              });
        return new Response(body, {
          headers: { "content-type": "application/json" },
        });
      }),
    );

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(false);
  });

  it("times out when the response stream stays silent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            new ReadableStream({
              start() {},
            }),
            { headers: { "content-type": "text/event-stream" } },
          ),
      ),
    );

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE, 10),
    ).rejects.toBeDefined();
  });

  it("marks disposable stdio bridge probes", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json({
        jsonrpc: "2.0",
        id: requestId(init),
        result: {},
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await probeMcpInitialize(
      "http://127.0.0.1/mcp",
      [{ name: MARKER, value: "1" }],
      MARKER,
      PROBE,
    );

    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({
      [MARKER]: "1",
      [PROBE]: "1",
    });
  });
});
