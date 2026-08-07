import { afterEach, describe, expect, it, vi } from "vitest";
import { probeMcpInitialize } from "./mcp-probe";

const MARKER = "x-posthog-agent-plugin-stdio-bridge";
const PROBE = "x-posthog-agent-plugin-stdio-probe";
const encoder = new TextEncoder();

function requestPayload(init?: RequestInit): Record<string, unknown> {
  return JSON.parse(String(init?.body)) as Record<string, unknown>;
}

function initializeResult(id: unknown): Record<string, unknown> {
  return {
    jsonrpc: "2.0",
    id,
    result: {
      protocolVersion: "2025-06-18",
      capabilities: {},
      serverInfo: { name: "probe-test", version: "1.0.0" },
    },
  };
}

function mcpFetch(
  initializeResponse: (
    id: unknown,
    init?: RequestInit,
  ) => Promise<Response> | Response,
): ReturnType<typeof vi.fn> {
  return vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      return new Response(null, { status: 200 });
    }
    const payload = requestPayload(init);
    if (payload.method === "notifications/initialized") {
      return new Response(null, { status: 202 });
    }
    if (payload.method === "initialize") {
      return initializeResponse(payload.id, init);
    }
    return new Response(null, { status: 404 });
  });
}

describe("Agent Plugin MCP initialize probe", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("completes the SDK handshake and terminates a returned session", async () => {
    const fetchMock = mcpFetch((id) =>
      Response.json(initializeResult(id), {
        headers: { "mcp-session-id": "probe-session" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(true);

    expect(
      fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE"),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(
        (call) =>
          call[1]?.body !== undefined &&
          requestPayload(call[1]).method === "notifications/initialized",
      ),
    ).toBe(true);
  });

  it("accepts a valid initialize event without waiting for SSE EOF", async () => {
    const fetchMock = mcpFetch(
      (id) =>
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  `event: message\ndata: ${JSON.stringify(initializeResult(id))}\n\n`,
                ),
              );
            },
          }),
          { headers: { "content-type": "text/event-stream" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(true);
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  });

  it.each([
    ["empty result", {}],
    ["malformed result", { protocolVersion: "2025-06-18" }],
    ["JSON-RPC error", null],
  ])("rejects an %s initialize response", async (_label, result) => {
    const fetchMock = mcpFetch((id) =>
      result === null
        ? Response.json({
            jsonrpc: "2.0",
            id,
            error: { code: -32603, message: "failed" },
          })
        : Response.json({ jsonrpc: "2.0", id, result }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE),
    ).resolves.toBe(false);
  });

  it("times out when an SSE stream stays silent", async () => {
    const fetchMock = mcpFetch(
      () =>
        new Response(new ReadableStream({ start() {} }), {
          headers: { "content-type": "text/event-stream" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      probeMcpInitialize("https://example.com/mcp", [], MARKER, PROBE, 10),
    ).rejects.toThrow("timed out");
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  });

  it("marks disposable stdio bridge probes", async () => {
    const fetchMock = mcpFetch((id) => Response.json(initializeResult(id)));
    vi.stubGlobal("fetch", fetchMock);

    await probeMcpInitialize(
      "http://127.0.0.1/mcp",
      [{ name: MARKER, value: "1" }],
      MARKER,
      PROBE,
    );

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get(MARKER)).toBe("1");
    expect(headers.get(PROBE)).toBe("1");
  });
});
