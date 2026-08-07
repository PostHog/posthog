import http from "node:http";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type {
  JSONRPCMessage,
  RequestId,
} from "@modelcontextprotocol/sdk/types.js";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable, preDestroy } from "inversify";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";

export const STDIO_BRIDGE_MARKER_HEADER = "x-posthog-agent-plugin-stdio-bridge";
export const STDIO_BRIDGE_PROBE_HEADER = "x-posthog-agent-plugin-stdio-probe";
const BRIDGE_ERROR_HEADER = "x-posthog-agent-plugin-proxy-error";

export interface AgentPluginStdioBridgeRegistration {
  id: string;
  runId: string;
  installationId: string;
  runtimeName: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  onFailure: (message: string) => void;
}

export interface AgentPluginStdioBridge {
  register(registration: AgentPluginStdioBridgeRegistration): Promise<string>;
  unregisterRun(runId: string): Promise<void>;
  unregisterInstallation(installationId: string): Promise<void>;
}

interface BridgeConnection {
  stdio: StdioClientTransport;
  http: StreamableHTTPServerTransport;
  pid: number;
  close: () => Promise<void>;
}

interface BridgeTarget extends AgentPluginStdioBridgeRegistration {
  connection?: BridgeConnection;
  connectionPromise?: Promise<BridgeConnection>;
  failureReported: boolean;
}

function relatedRequestId(message: JSONRPCMessage): RequestId | undefined {
  if (
    "id" in message &&
    ("result" in message || "error" in message) &&
    message.id !== null
  ) {
    return message.id;
  }
  return undefined;
}

@injectable()
export class AgentPluginStdioBridgeService implements AgentPluginStdioBridge {
  private server: http.Server | null = null;
  private port: number | null = null;
  private startPromise: Promise<void> | null = null;
  private readonly targets = new Map<string, BridgeTarget>();
  private readonly log: ScopedLogger;

  constructor(
    @inject(PROCESS_TRACKING_SERVICE)
    private readonly processTracking: ProcessTrackingService,
    @inject(ROOT_LOGGER) logger: RootLogger,
  ) {
    this.log = logger.scope("agent-plugin-stdio-bridge");
  }

  async register(
    registration: AgentPluginStdioBridgeRegistration,
  ): Promise<string> {
    await this.start();
    const existing = this.targets.get(registration.id);
    if (existing) await this.closeTarget(existing);
    this.targets.set(registration.id, {
      ...registration,
      failureReported: false,
    });
    return `http://127.0.0.1:${this.port}/${encodeURIComponent(registration.id)}`;
  }

  async unregisterRun(runId: string): Promise<void> {
    await this.unregisterMatching((target) => target.runId === runId);
  }

  async unregisterInstallation(installationId: string): Promise<void> {
    await this.unregisterMatching(
      (target) => target.installationId === installationId,
    );
  }

  @preDestroy()
  async stop(): Promise<void> {
    await Promise.all(
      [...this.targets.values()].map((target) => this.closeTarget(target)),
    );
    this.targets.clear();
    if (!this.server) return;

    const server = this.server;
    await new Promise<void>((resolve) => {
      server.close(() => resolve());
      server.closeAllConnections();
    });
    this.server = null;
    this.port = null;
    this.startPromise = null;
  }

  protected createStdioTransport(
    registration: AgentPluginStdioBridgeRegistration,
  ): StdioClientTransport {
    return new StdioClientTransport({
      command: registration.command,
      args: registration.args,
      env: registration.env,
      cwd: registration.cwd,
      stderr: "pipe",
    });
  }

  protected createHttpTransport(): StreamableHTTPServerTransport {
    return new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  }

  private async unregisterMatching(
    predicate: (target: BridgeTarget) => boolean,
  ): Promise<void> {
    const matches = [...this.targets.entries()].filter(([, target]) =>
      predicate(target),
    );
    await Promise.all(
      matches.map(async ([id, target]) => {
        this.targets.delete(id);
        await this.closeTarget(target);
      }),
    );
  }

  private async closeTarget(target: BridgeTarget): Promise<void> {
    let connection = target.connection;
    if (!connection && target.connectionPromise) {
      try {
        connection = await target.connectionPromise;
      } catch {
        return;
      }
    }
    target.connection = undefined;
    target.connectionPromise = undefined;
    await connection?.close();
  }

  private async start(): Promise<void> {
    if (this.server && this.port !== null) return;
    if (this.startPromise) return this.startPromise;
    this.startPromise = this.startServer().catch((error) => {
      this.startPromise = null;
      throw error;
    });
    return this.startPromise;
  }

  private async startServer(): Promise<void> {
    const server = http.createServer((request, response) => {
      void this.handleRequest(request, response).catch((error) => {
        this.log.warn("Agent Plugin stdio bridge request failed", {
          error: error instanceof Error ? error.message : String(error),
        });
        if (!response.headersSent) {
          response.writeHead(502, { [BRIDGE_ERROR_HEADER]: "1" });
        }
        response.end("Agent Plugin stdio bridge error");
      });
    });
    this.server = server;
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        server.off("error", reject);
        const address = server.address();
        if (typeof address !== "object" || address === null) {
          reject(new Error("Failed to start Agent Plugin stdio bridge."));
          return;
        }
        this.port = address.port;
        server.on("error", (error) => {
          this.log.error("Agent Plugin stdio bridge server failed", error);
        });
        resolve();
      });
    });
  }

  private async handleRequest(
    request: http.IncomingMessage,
    response: http.ServerResponse,
  ): Promise<void> {
    const incomingUrl = new URL(request.url ?? "/", "http://localhost");
    const rawId = incomingUrl.pathname.split("/").filter(Boolean)[0];
    const id = rawId ? decodeURIComponent(rawId) : "";
    const target = this.targets.get(id);
    if (!target) {
      response.writeHead(404);
      response.end("Unknown Agent Plugin stdio target");
      return;
    }

    const isProbe = request.headers[STDIO_BRIDGE_PROBE_HEADER] === "1";
    const connection = isProbe
      ? await this.startConnection(target, true)
      : await this.getOrStartConnection(target);
    try {
      await connection.http.handleRequest(request, response);
    } finally {
      if (isProbe) await connection.close();
    }
  }

  private getOrStartConnection(
    target: BridgeTarget,
  ): Promise<BridgeConnection> {
    if (target.connection) return Promise.resolve(target.connection);
    if (target.connectionPromise) return target.connectionPromise;

    target.connectionPromise = this.startConnection(target, false)
      .then((connection) => {
        target.connection = connection;
        target.connectionPromise = undefined;
        return connection;
      })
      .catch((error) => {
        target.connectionPromise = undefined;
        this.reportFailure(target, error);
        throw error;
      });
    return target.connectionPromise;
  }

  private async startConnection(
    target: BridgeTarget,
    ephemeral: boolean,
  ): Promise<BridgeConnection> {
    const stdio = this.createStdioTransport(target);
    const httpTransport = this.createHttpTransport();
    let connection: BridgeConnection | undefined;
    let intentionallyClosing = false;

    httpTransport.onmessage = (message) => {
      void stdio.send(message).catch((error) => {
        this.reportFailure(target, error);
        void httpTransport.close();
      });
    };
    stdio.onmessage = (message) => {
      const requestId = relatedRequestId(message);
      void httpTransport
        .send(
          message,
          requestId === undefined ? undefined : { relatedRequestId: requestId },
        )
        .catch((error) => {
          if (requestId !== undefined || "id" in message) {
            this.reportFailure(target, error);
          } else {
            this.log.debug(
              "Dropped stdio MCP notification without a client stream",
            );
          }
        });
    };
    stdio.onerror = (error) => this.reportFailure(target, error);
    stdio.onclose = () => {
      if (connection) {
        this.processTracking.unregister(connection.pid, "mcp-exited");
        if (!ephemeral && target.connection === connection) {
          target.connection = undefined;
        }
      }
      if (!intentionallyClosing) {
        this.reportFailure(
          target,
          new Error("The stdio MCP server stopped unexpectedly."),
        );
      }
      void httpTransport.close();
    };

    await httpTransport.start();
    try {
      await stdio.start();
    } catch (error) {
      await httpTransport.close();
      this.reportFailure(target, error);
      throw error;
    }
    const pid = stdio.pid;
    if (pid === null) {
      await Promise.all([stdio.close(), httpTransport.close()]);
      throw new Error("Agent Plugin stdio server did not start.");
    }

    stdio.stderr?.on("data", () => undefined);
    this.processTracking.register(
      pid,
      "child",
      `agent-plugin:${target.runtimeName}`,
      {
        taskRunId: target.runId,
        installationId: target.installationId,
        server: target.runtimeName,
      },
      target.runId,
    );

    let closed = false;
    connection = {
      stdio,
      http: httpTransport,
      pid,
      close: async () => {
        if (closed) return;
        closed = true;
        intentionallyClosing = true;
        await httpTransport.close();
        this.processTracking.kill(pid);
        await stdio.close();
      },
    };
    return connection;
  }

  private reportFailure(target: BridgeTarget, error: unknown): void {
    if (target.failureReported) return;
    target.failureReported = true;
    target.onFailure(
      error instanceof Error && error.message
        ? error.message
        : "The stdio MCP server stopped unexpectedly.",
    );
  }
}
