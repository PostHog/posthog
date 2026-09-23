import { randomUUID } from "node:crypto";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";
import type { McpServer } from "@agentclientprotocol/sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { createBrowserMcpServer } from "@posthog/agent/browser-mcp";
import { injectable, preDestroy } from "inversify";
import type { BrowserConnectionStatus } from "./schemas";

export const BROWSER_CONNECTION = Symbol.for(
  "posthog.workspace.browserConnection",
);

@injectable()
export class BrowserConnection {
  private client: Client | undefined;
  private starting: Promise<Client> | undefined;
  private listener: ReturnType<typeof createServer> | undefined;
  private listening: Promise<number> | undefined;
  private readonly tokens = new Map<string, string>();
  private readonly authorizedSessions = new Set<string>();
  private blocked = true;
  private generation = 0;
  private status: BrowserConnectionStatus["status"] = "idle";

  getStatus(): BrowserConnectionStatus {
    return { status: this.status };
  }

  async getServer(sessionId: string): Promise<McpServer> {
    this.listening ??= this.listen().catch((error) => {
      this.listening = undefined;
      throw error;
    });
    const port = await this.listening;
    let token = this.tokens.get(sessionId);
    if (!token) {
      token = randomUUID();
      this.tokens.set(sessionId, token);
    }
    return {
      name: "posthog-browser",
      type: "http",
      url: `http://127.0.0.1:${port}/mcp`,
      headers: [{ name: "Authorization", value: `Bearer ${token}` }],
    };
  }

  releaseSession(sessionId: string): void {
    this.tokens.delete(sessionId);
    this.authorizedSessions.delete(sessionId);
  }

  private async getClient(allowDisconnected = false): Promise<Client> {
    if (this.blocked && !allowDisconnected) {
      throw new Error(
        "Chrome is disconnected. Select Connect Chrome in Settings > Advanced > Browser access.",
      );
    }
    if (this.starting) return this.starting;
    if (this.client) return this.client;
    const generation = this.generation;
    const client = new Client({
      name: "posthog-desktop-browser",
      version: "1.0.0",
    });
    const descriptor = createBrowserMcpServer();
    const transport = new StdioClientTransport({
      command: descriptor.command,
      args: descriptor.args,
      env: Object.fromEntries(
        descriptor.env.map(({ name, value }) => [name, value]),
      ),
      stderr: "ignore",
    });
    this.client = client;
    client.onclose = () => {
      if (this.client !== client) return;
      this.client = undefined;
      this.blocked = true;
      this.status = "disconnected";
    };
    this.starting = client
      .connect(transport)
      .then(async () => {
        if (generation !== this.generation) {
          await client.close();
          throw new Error(
            "Chrome connection canceled. Reconnect in Settings > Advanced > Browser access.",
          );
        }
        return client;
      })
      .catch(async (error) => {
        if (generation === this.generation) {
          this.client = undefined;
          this.blocked = true;
          this.status = "error";
        }
        await client.close();
        throw error;
      })
      .finally(() => {
        if (generation === this.generation) this.starting = undefined;
      });
    return this.starting;
  }

  async reconnect(): Promise<void> {
    if (this.status === "connecting") return;
    const closing = this.disconnect();
    const generation = this.generation;
    await closing;
    if (generation !== this.generation) return;
    this.blocked = false;
    this.authorizedSessions.clear();
    for (const sessionId of this.tokens.keys()) {
      this.authorizedSessions.add(sessionId);
    }
    this.status = "connecting";
    try {
      const client = await this.getClient();
      const result = await this.callTool(client, {
        name: "list_pages",
        arguments: {},
      });
      if (result.isError) {
        throw new Error(
          "Couldn't connect to Chrome. Check Chrome and try again.",
        );
      }
    } catch (error) {
      if (generation === this.generation) {
        this.blocked = true;
        this.status = "error";
      }
      throw error;
    }
  }

  async disconnect(): Promise<void> {
    this.blocked = true;
    this.authorizedSessions.clear();
    this.status = "disconnected";
    this.generation++;
    const client = this.client;
    this.client = undefined;
    this.starting = undefined;
    await client?.close();
  }

  private async callTool(
    client: Client,
    params: { name: string; arguments?: Record<string, unknown> },
    signal?: AbortSignal,
  ): ReturnType<Client["callTool"]> {
    if (this.blocked || this.client !== client) {
      throw new Error(
        "Chrome is disconnected. Select Connect Chrome in Settings > Advanced > Browser access.",
      );
    }
    const wasConnected = this.status === "connected";
    if (!wasConnected) this.status = "connecting";
    try {
      const result = await client.callTool(params, undefined, {
        timeout: 60_000,
        signal,
      });
      if (this.client === client)
        this.status = result.isError && !wasConnected ? "error" : "connected";
      return result;
    } catch (error) {
      if (this.client === client && !wasConnected) this.status = "error";
      throw error;
    }
  }

  private async handleRequest(
    req: IncomingMessage,
    res: ServerResponse,
  ): Promise<void> {
    const sessionId = [...this.tokens].find(
      ([, token]) => req.headers.authorization === `Bearer ${token}`,
    )?.[0];
    if (req.headers.origin || !sessionId) {
      res.writeHead(403).end();
      return;
    }
    if (req.url !== "/mcp") {
      res.writeHead(404).end();
      return;
    }
    const server = new Server(
      { name: "posthog-desktop-browser", version: "1.0.0" },
      { capabilities: { tools: {} } },
    );
    server.setRequestHandler(ListToolsRequestSchema, async () => {
      const client = await this.getClient(true);
      const result = await client.listTools();
      return {
        ...result,
        tools: result.tools.filter((tool) => tool.name !== "select_page"),
      };
    });
    server.setRequestHandler(
      CallToolRequestSchema,
      async ({ params }, extra) => {
        if (this.blocked) {
          throw new Error(
            "Chrome is disconnected. Select Connect Chrome in Settings > Advanced > Browser access.",
          );
        }
        if (!this.authorizedSessions.has(sessionId)) {
          throw new Error(
            "Chrome access is not allowed for this session. Select Allow sessions in Settings > Advanced > Browser access.",
          );
        }
        if (params.name === "select_page")
          throw new Error("Use an explicit pageId for browser actions.");
        const client = await this.getClient();
        return this.callTool(client, params, extra.signal);
      },
    );
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    res.on("close", () => {
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res);
  }

  private async listen(): Promise<number> {
    const listener = createServer((req, res) => {
      void this.handleRequest(req, res).catch(() => {
        if (!res.headersSent) res.writeHead(500);
        res.end();
      });
    });
    this.listener = listener;
    await new Promise<void>((resolve, reject) => {
      listener.once("error", reject);
      listener.listen(0, "127.0.0.1", resolve);
    });
    return (listener.address() as AddressInfo).port;
  }

  @preDestroy()
  async close(): Promise<void> {
    this.tokens.clear();
    this.authorizedSessions.clear();
    await this.disconnect();
    const listener = this.listener;
    this.listener = undefined;
    this.listening = undefined;
    listener?.closeAllConnections();
    if (listener)
      await new Promise<void>((resolve) => listener.close(() => resolve()));
  }
}
