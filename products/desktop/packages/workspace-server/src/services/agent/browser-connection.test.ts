import "reflect-metadata";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserConnection } from "./browser-connection";

const upstream = vi.hoisted(() => ({
  starts: 0,
  calls: vi.fn(),
  transports: [] as Array<{ close(): Promise<void> }>,
}));
vi.mock("@modelcontextprotocol/sdk/client/stdio.js", () => ({
  StdioClientTransport: vi.fn(function MockStdioClientTransport() {
    upstream.starts++;
    const [client, transport] = InMemoryTransport.createLinkedPair();
    upstream.transports.push(transport);
    const server = new Server(
      { name: "test-browser", version: "1.0.0" },
      { capabilities: { tools: {} } },
    );
    server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        { name: "list_pages", inputSchema: { type: "object" } },
        { name: "select_page", inputSchema: { type: "object" } },
        {
          name: "take_snapshot",
          inputSchema: {
            type: "object",
            properties: { pageId: { type: "number" } },
            required: ["pageId"],
          },
        },
      ],
    }));
    server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
      await upstream.calls(params);
      return { content: [{ type: "text", text: JSON.stringify(params) }] };
    });
    void server.connect(transport);
    return client;
  }),
}));

vi.mock("@posthog/agent/browser-mcp", () => ({
  createBrowserMcpServer: () => ({
    command: "test-browser",
    args: [],
    env: [],
  }),
}));

describe("BrowserConnection", () => {
  let connection: BrowserConnection;
  const clients: Client[] = [];

  beforeEach(() => {
    connection = new BrowserConnection();
    upstream.starts = 0;
    upstream.transports = [];
    upstream.calls.mockReset();
  });

  afterEach(async () => {
    await Promise.all(clients.splice(0).map((client) => client.close()));
    await connection.close();
  });

  async function connect(sessionId: string): Promise<Client> {
    const descriptor = await connection.getServer(sessionId);
    if (!("url" in descriptor)) throw new Error("Expected HTTP MCP server");
    const client = new Client({ name: sessionId, version: "1.0.0" });
    clients.push(client);
    await client.connect(
      new StreamableHTTPClientTransport(new URL(descriptor.url), {
        requestInit: {
          headers: Object.fromEntries(
            descriptor.headers.map(({ name, value }) => [name, value]),
          ),
        },
      }),
    );
    return client;
  }

  it("discovers tools without browser access and connects without replacing the session", async () => {
    const client = await connect("session");
    const descriptor = await connection.getServer("session");
    expect(descriptor.name).toBe("posthog-browser");
    expect((await client.listTools()).tools.map((tool) => tool.name)).toContain(
      "list_pages",
    );
    expect(upstream.calls).not.toHaveBeenCalled();
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome is disconnected",
    );
    expect(upstream.calls).not.toHaveBeenCalled();
    await connection.reconnect();
    await client.callTool({ name: "list_pages" });
    await connection.disconnect();
    await client.listTools();
    upstream.calls.mockClear();
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome is disconnected",
    );
    expect(upstream.calls).not.toHaveBeenCalled();
  });

  it("shares one browser across concurrent sessions and keeps it after a session ends", async () => {
    const [first, second] = await Promise.all([
      connect("first"),
      connect("second"),
    ]);
    const lists = await Promise.all([first.listTools(), second.listTools()]);
    expect(upstream.starts).toBe(1);
    expect(upstream.calls).not.toHaveBeenCalled();
    expect(lists[0].tools.map((tool) => tool.name)).not.toContain(
      "select_page",
    );
    await connection.reconnect();
    await Promise.all([
      first.callTool({ name: "take_snapshot", arguments: { pageId: 11 } }),
      second.callTool({ name: "take_snapshot", arguments: { pageId: 22 } }),
    ]);
    expect(upstream.calls).toHaveBeenCalledWith({
      name: "take_snapshot",
      arguments: { pageId: 11 },
    });
    expect(upstream.calls).toHaveBeenCalledWith({
      name: "take_snapshot",
      arguments: { pageId: 22 },
    });
    connection.releaseSession("first");
    await expect(first.callTool({ name: "list_pages" })).rejects.toThrow();
    await second.callTool({ name: "list_pages" });
    await first.close();
    const third = await connect("third");
    await expect(third.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome access is not allowed for this session",
    );
    await second.callTool({ name: "list_pages" });
    await connection.reconnect();
    await third.callTool({ name: "list_pages" });
    expect(upstream.starts).toBe(3);
  });

  it("blocks calls after disconnect until explicit reconnect", async () => {
    const client = await connect("session");
    await connection.reconnect();
    await client.callTool({ name: "list_pages" });
    expect(connection.getStatus().status).toBe("connected");
    await connection.disconnect();
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome is disconnected",
    );
    expect(upstream.starts).toBe(1);
    await connection.reconnect();
    await client.callTool({ name: "list_pages" });
    expect(connection.getStatus().status).toBe("connected");
    expect(upstream.starts).toBe(2);
  });

  it("keeps the same connection after a failed browser action", async () => {
    const client = await connect("session");
    await connection.reconnect();
    upstream.calls.mockRejectedValueOnce(new Error("Browser action timed out"));
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Browser action timed out",
    );
    expect(connection.getStatus().status).toBe("connected");
    await client.callTool({ name: "list_pages" });
    expect(upstream.starts).toBe(1);
    expect(connection.getStatus().status).toBe("connected");
  });

  it("requires explicit reconnect after a connection attempt fails", async () => {
    const client = await connect("session");
    upstream.calls.mockRejectedValueOnce(new Error("Connection failed"));
    await expect(connection.reconnect()).rejects.toThrow("Connection failed");
    expect(connection.getStatus().status).toBe("error");
    await client.listTools();
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome is disconnected",
    );
    expect(upstream.calls).toHaveBeenCalledTimes(1);
    await connection.reconnect();
    await client.callTool({ name: "list_pages" });
    expect(connection.getStatus().status).toBe("connected");
  });

  it("requires explicit reconnect after the browser process exits", async () => {
    const client = await connect("session");
    await connection.reconnect();
    await client.callTool({ name: "list_pages" });
    await upstream.transports[0].close();
    expect(connection.getStatus().status).toBe("disconnected");
    await expect(client.callTool({ name: "list_pages" })).rejects.toThrow(
      "Chrome is disconnected",
    );
    expect(upstream.starts).toBe(1);
    await connection.reconnect();
    expect(connection.getStatus().status).toBe("connected");
    expect(upstream.starts).toBe(2);
  });

  it("rejects unauthenticated requests and browser origins", async () => {
    const descriptor = await connection.getServer("session");
    if (!("url" in descriptor)) throw new Error("Expected HTTP MCP server");
    const unauthorized = await fetch(descriptor.url, { method: "POST" });
    expect(unauthorized.status).toBe(403);
    const browserRequest = await fetch(descriptor.url, {
      method: "POST",
      headers: {
        ...Object.fromEntries(
          descriptor.headers.map(({ name, value }) => [name, value]),
        ),
        Origin: "https://example.com",
      },
    });
    expect(browserRequest.status).toBe(403);
    expect(upstream.starts).toBe(0);
  });
});
