import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";
import type { ClaudeJsonMcpServerEntry } from "@posthog/agent/adapters/claude/session/mcp-config";
import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it } from "vitest";
import { McpRelayServiceImpl } from "./mcp-relay";

const fakeLogger: RootLogger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
  scope: () => fakeLogger,
};

class FakeTransport implements Transport {
  started = false;
  closed = false;
  sent: Record<string, unknown>[] = [];
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;

  async start(): Promise<void> {
    this.started = true;
  }

  async send(message: JSONRPCMessage): Promise<void> {
    this.sent.push(message as Record<string, unknown>);
  }

  async close(): Promise<void> {
    this.closed = true;
    this.onclose?.();
  }

  respond(message: Record<string, unknown>): void {
    this.onmessage?.(message as JSONRPCMessage);
  }
}

class TestMcpRelayService extends McpRelayServiceImpl {
  entries: ClaudeJsonMcpServerEntry[] = [];
  transports: FakeTransport[] = [];
  factoryCalls = 0;
  failNextStart = false;
  protected override responseTimeoutMs = 25;

  constructor() {
    super(fakeLogger);
  }

  protected override loadServerEntries(): ClaudeJsonMcpServerEntry[] {
    return this.entries;
  }

  protected override createTransport(): Transport {
    this.factoryCalls += 1;
    const transport = new FakeTransport();
    if (this.failNextStart) {
      this.failNextStart = false;
      transport.start = async () => {
        throw new Error("spawn ENOENT");
      };
    }
    this.transports.push(transport);
    return transport;
  }
}

function stdioEntry(name: string): ClaudeJsonMcpServerEntry {
  return {
    name,
    scope: "user",
    config: { type: "stdio", command: "noop" },
  };
}

function makeService(...serverNames: string[]): TestMcpRelayService {
  const service = new TestMcpRelayService();
  service.entries = serverNames.map(stdioEntry);
  return service;
}

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("McpRelayServiceImpl", () => {
  it("rejects an unknown server name without connecting", async () => {
    const service = makeService("known");

    const execution = await service.execute("run-1", "unknown", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list",
    });

    expect(execution.error).toEqual({
      code: -32601,
      message: "Unknown local MCP server: unknown",
    });
    expect(service.factoryCalls).toBe(0);
  });

  it("remaps colliding JSON-RPC ids across runs and restores them", async () => {
    const service = makeService("srv");

    const first = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 5,
      method: "tools/call",
      params: { name: "a" },
    });
    const second = service.execute("run-2", "srv", {
      jsonrpc: "2.0",
      id: 5,
      method: "tools/call",
      params: { name: "b" },
    });
    await flush();

    // One real connection per (runId, server); each remaps to its own id-space.
    expect(service.transports).toHaveLength(2);
    const [transportA, transportB] = service.transports;
    expect(transportA.sent[0]).toMatchObject({ id: 1, params: { name: "a" } });
    expect(transportB.sent[0]).toMatchObject({ id: 1, params: { name: "b" } });

    transportA.respond({ jsonrpc: "2.0", id: 1, result: { from: "a" } });
    transportB.respond({ jsonrpc: "2.0", id: 1, result: { from: "b" } });

    expect(await first).toEqual({
      payload: { jsonrpc: "2.0", id: 5, result: { from: "a" } },
    });
    expect(await second).toEqual({
      payload: { jsonrpc: "2.0", id: 5, result: { from: "b" } },
    });
  });

  it("remaps concurrent requests with the same id on one connection", async () => {
    const service = makeService("srv");

    const first = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 5,
      method: "tools/call",
    });
    const second = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 5,
      method: "resources/read",
    });
    await flush();

    expect(service.transports).toHaveLength(1);
    const [transport] = service.transports;
    expect(transport.sent.map((message) => message.id)).toEqual([1, 2]);

    transport.respond({ jsonrpc: "2.0", id: 2, result: { order: "second" } });
    transport.respond({ jsonrpc: "2.0", id: 1, result: { order: "first" } });

    expect(await first).toEqual({
      payload: { jsonrpc: "2.0", id: 5, result: { order: "first" } },
    });
    expect(await second).toEqual({
      payload: { jsonrpc: "2.0", id: 5, result: { order: "second" } },
    });
  });

  it("sends notifications fire-and-forget without a pending entry", async () => {
    const service = makeService("srv");

    const execution = await service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });

    expect(execution).toEqual({});
    expect(service.transports[0].sent).toEqual([
      { jsonrpc: "2.0", method: "notifications/initialized" },
    ]);
  });

  it("treats an explicit null id the same as a missing id (fire-and-forget)", async () => {
    const service = makeService("srv");

    const execution = await service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: null,
      method: "notifications/initialized",
    });

    expect(execution).toEqual({});
    expect(service.transports[0].sent).toEqual([
      { jsonrpc: "2.0", id: null, method: "notifications/initialized" },
    ]);
  });

  it("replaces a response over 256 KB with a -32003 error", async () => {
    const service = makeService("srv");

    const execution = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 1,
      method: "resources/read",
    });
    await flush();

    service.transports[0].respond({
      jsonrpc: "2.0",
      id: 1,
      result: { blob: "x".repeat(260_000) },
    });

    expect(await execution).toEqual({
      error: { code: -32003, message: "Relayed MCP response exceeds 256 KB" },
    });
  });

  it("reports a start failure as -32000 and retries on the next execute", async () => {
    const service = makeService("srv");
    service.failNextStart = true;

    const failed = await service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list",
    });
    expect(failed.error).toEqual({ code: -32000, message: "spawn ENOENT" });
    expect(service.factoryCalls).toBe(1);

    // The failed connection was evicted, so the next execute reconnects.
    const retried = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/list",
    });
    await flush();
    expect(service.factoryCalls).toBe(2);

    service.transports[1].respond({ jsonrpc: "2.0", id: 1, result: {} });
    expect(await retried).toEqual({
      payload: { jsonrpc: "2.0", id: 2, result: {} },
    });
  });

  it("closes only the given run's transports on closeRun", async () => {
    const service = makeService("srv", "other");
    await service.execute("run-1", "srv", { jsonrpc: "2.0", method: "ping" });
    await service.execute("run-1", "other", { jsonrpc: "2.0", method: "ping" });
    await service.execute("run-2", "srv", { jsonrpc: "2.0", method: "ping" });
    expect(service.transports).toHaveLength(3);

    await service.closeRun("run-1");

    expect(service.transports.map((t) => t.closed)).toEqual([
      true,
      true,
      false,
    ]);

    // A closed run lazily reconnects on its next execute.
    await service.execute("run-1", "srv", { jsonrpc: "2.0", method: "ping" });
    expect(service.factoryCalls).toBe(4);
  });

  it("closes everything on dispose", async () => {
    const service = makeService("srv");
    await service.execute("run-1", "srv", { jsonrpc: "2.0", method: "ping" });
    await service.execute("run-2", "srv", { jsonrpc: "2.0", method: "ping" });

    await service.dispose();

    expect(service.transports.map((t) => t.closed)).toEqual([true, true]);
  });

  it("resolves with -32001 when the server never responds", async () => {
    const service = makeService("srv");

    const execution = await service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
    });

    expect(execution).toEqual({
      error: { code: -32001, message: "Local MCP server did not respond" },
    });
  });

  it("fails pending requests when the connection closes mid-call", async () => {
    const service = makeService("srv");

    const execution = service.execute("run-1", "srv", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
    });
    await flush();

    service.transports[0].onclose?.();

    expect(await execution).toEqual({
      error: {
        code: -32000,
        message: 'Connection to local MCP server "srv" closed',
      },
    });

    // The dropped connection was evicted, so the next execute reconnects.
    await service.execute("run-1", "srv", { jsonrpc: "2.0", method: "ping" });
    expect(service.factoryCalls).toBe(2);
  });
});
