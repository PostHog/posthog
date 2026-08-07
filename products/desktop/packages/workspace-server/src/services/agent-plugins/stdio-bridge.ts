import * as crypto from "node:crypto";
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
const MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024;

export interface AgentPluginStdioLaunchConfig {
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
}

export interface AgentPluginStdioBridgeRegistration {
  id: string;
  taskId: string;
  runId: string;
  installationId: string;
  runtimeName: string;
  prepare: () => Promise<AgentPluginStdioLaunchConfig>;
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

interface PendingLaunch {
  abortController: AbortController;
  promise: Promise<BridgeConnection>;
}

interface BridgeTarget extends AgentPluginStdioBridgeRegistration {
  routeToken: string;
  connection?: BridgeConnection;
  connectionPromise?: Promise<BridgeConnection>;
  launches: Set<PendingLaunch>;
  failureReported: boolean;
  active: boolean;
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

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "The stdio MCP server stopped unexpectedly.";
}

class RequestBodyTooLargeError extends Error {}

@injectable()
export class AgentPluginStdioBridgeService implements AgentPluginStdioBridge {
  private server: http.Server | null = null;
  private port: number | null = null;
  private startPromise: Promise<void> | null = null;
  private readonly targets = new Map<string, BridgeTarget>();
  private readonly routeByRegistration = new Map<string, string>();
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
    const existingRoute = this.routeByRegistration.get(registration.id);
    if (existingRoute) await this.unregisterRoute(existingRoute);

    const routeToken = crypto.randomBytes(32).toString("base64url");
    const target: BridgeTarget = {
      ...registration,
      routeToken,
      launches: new Set(),
      failureReported: false,
      active: true,
    };
    this.targets.set(routeToken, target);
    this.routeByRegistration.set(registration.id, routeToken);
    return `http://127.0.0.1:${this.port}/${routeToken}`;
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
      [...this.targets.keys()].map((routeToken) =>
        this.unregisterRoute(routeToken),
      ),
    );
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
    config: AgentPluginStdioLaunchConfig,
  ): StdioClientTransport {
    return new StdioClientTransport({
      command: config.command,
      args: config.args,
      env: config.env,
      cwd: config.cwd,
      stderr: "pipe",
    });
  }

  protected createHttpTransport(): StreamableHTTPServerTransport {
    return new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  }

  private async unregisterMatching(
    predicate: (target: BridgeTarget) => boolean,
  ): Promise<void> {
    const routes = [...this.targets.entries()]
      .filter(([, target]) => predicate(target))
      .map(([routeToken]) => routeToken);
    await Promise.all(
      routes.map((routeToken) => this.unregisterRoute(routeToken)),
    );
  }

  private async unregisterRoute(routeToken: string): Promise<void> {
    const target = this.targets.get(routeToken);
    if (!target) return;
    this.targets.delete(routeToken);
    target.active = false;
    if (this.routeByRegistration.get(target.id) === routeToken) {
      this.routeByRegistration.delete(target.id);
    }

    const launches = [...target.launches];
    for (const launch of launches) {
      launch.abortController.abort(
        new Error("Agent Plugin stdio target was removed."),
      );
    }
    const launchedConnections = await Promise.allSettled(
      launches.map((launch) => launch.promise),
    );
    await Promise.allSettled(
      launchedConnections.flatMap((result) =>
        result.status === "fulfilled" ? [result.value.close()] : [],
      ),
    );
    target.launches.clear();
    await this.closeTarget(target);
  }

  private async closeTarget(target: BridgeTarget): Promise<void> {
    let connection = target.connection;
    if (!connection && target.connectionPromise) {
      try {
        connection = await target.connectionPromise;
      } catch {
        connection = undefined;
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
      this.server?.closeAllConnections();
      this.server?.close();
      this.server = null;
      this.port = null;
      this.startPromise = null;
      throw error;
    });
    return this.startPromise;
  }

  private async startServer(): Promise<void> {
    const server = http.createServer((request, response) => {
      void this.handleRequest(request, response).catch((error) => {
        this.log.warn("Agent Plugin stdio bridge request failed", {
          error: errorMessage(error),
        });
        if (!response.headersSent) {
          response.writeHead(
            error instanceof RequestBodyTooLargeError ? 413 : 502,
            { [BRIDGE_ERROR_HEADER]: "1" },
          );
        }
        response.end(
          error instanceof RequestBodyTooLargeError
            ? "Agent Plugin MCP request body is too large"
            : "Agent Plugin stdio bridge error",
        );
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
    if (request.headers.origin || request.headers["sec-fetch-site"]) {
      response.writeHead(403);
      response.end("Browser requests are not allowed");
      return;
    }

    const incomingUrl = new URL(request.url ?? "/", "http://localhost");
    const routeToken = incomingUrl.pathname.split("/").filter(Boolean)[0];
    const target = routeToken ? this.targets.get(routeToken) : undefined;
    if (!target || !target.active) {
      response.writeHead(404);
      response.end("Unknown Agent Plugin stdio target");
      return;
    }

    let parsedBody: unknown;
    if (request.method !== "GET" && request.method !== "HEAD") {
      const body = await this.readRequestBody(request);
      try {
        parsedBody = JSON.parse(body.toString("utf8"));
      } catch {
        response.writeHead(400);
        response.end("Agent Plugin MCP request body is not valid JSON");
        return;
      }
    }

    const isProbe = request.headers[STDIO_BRIDGE_PROBE_HEADER] === "1";
    if (isProbe) {
      const launch = this.beginConnection(target);
      let connection: BridgeConnection | undefined;
      try {
        connection = await launch.promise;
        await connection.http.handleRequest(request, response, parsedBody);
      } finally {
        await connection?.close();
        target.launches.delete(launch);
      }
      return;
    }

    const connection = await this.getOrStartConnection(target);
    try {
      await connection.http.handleRequest(request, response, parsedBody);
    } catch (error) {
      this.invalidateConnection(target, connection, error);
      throw error;
    }
  }

  private readRequestBody(request: http.IncomingMessage): Promise<Buffer> {
    const contentLength = Number(request.headers["content-length"] ?? 0);
    if (
      Number.isFinite(contentLength) &&
      contentLength > MAX_REQUEST_BODY_BYTES
    ) {
      return Promise.reject(new RequestBodyTooLargeError());
    }
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      let size = 0;
      request.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > MAX_REQUEST_BODY_BYTES) {
          reject(new RequestBodyTooLargeError());
          request.destroy();
          return;
        }
        chunks.push(chunk);
      });
      request.on("end", () => resolve(Buffer.concat(chunks)));
      request.on("error", reject);
    });
  }

  private getOrStartConnection(
    target: BridgeTarget,
  ): Promise<BridgeConnection> {
    if (target.connection) return Promise.resolve(target.connection);
    if (target.connectionPromise) return target.connectionPromise;

    const launch = this.beginConnection(target);
    const startPromise = launch.promise
      .then(async (connection) => {
        this.assertLaunchActive(target, launch.abortController.signal);
        target.connection = connection;
        target.connectionPromise = undefined;
        target.launches.delete(launch);
        target.failureReported = false;
        return connection;
      })
      .catch((error) => {
        target.launches.delete(launch);
        if (target.connectionPromise === startPromise) {
          target.connectionPromise = undefined;
        }
        this.reportFailure(target, error);
        throw error;
      });
    target.connectionPromise = startPromise;
    return startPromise;
  }

  private beginConnection(target: BridgeTarget): PendingLaunch {
    const abortController = new AbortController();
    const launch = {
      abortController,
      promise: Promise.resolve().then(() =>
        this.startConnection(target, abortController.signal),
      ),
    };
    target.launches.add(launch);
    return launch;
  }

  private assertLaunchActive(target: BridgeTarget, signal: AbortSignal): void {
    if (!target.active || signal.aborted) {
      throw (
        signal.reason ?? new Error("Agent Plugin stdio target was removed.")
      );
    }
  }

  private async startConnection(
    target: BridgeTarget,
    signal: AbortSignal,
  ): Promise<BridgeConnection> {
    this.assertLaunchActive(target, signal);
    const config = await target.prepare();
    this.assertLaunchActive(target, signal);
    const stdio = this.createStdioTransport(config);
    const httpTransport = this.createHttpTransport();
    let connection: BridgeConnection | undefined;
    let intentionallyClosing = false;

    const fail = (error: unknown): void => {
      if (intentionallyClosing) return;
      if (connection) {
        this.invalidateConnection(target, connection, error);
      } else {
        this.reportFailure(target, error);
      }
    };

    httpTransport.onmessage = (message) => {
      void stdio.send(message).catch(fail);
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
            fail(error);
          } else {
            this.log.debug(
              "Dropped stdio MCP notification without a client stream",
            );
          }
        });
    };
    stdio.onerror = fail;
    stdio.onclose = () => {
      if (connection) {
        this.processTracking.unregister(connection.pid, "mcp-exited");
      }
      fail(new Error("The stdio MCP server stopped unexpectedly."));
    };

    const abortStartup = (): void => {
      intentionallyClosing = true;
      void Promise.allSettled([httpTransport.close(), stdio.close()]);
    };
    signal.addEventListener("abort", abortStartup, { once: true });

    try {
      await httpTransport.start();
      this.assertLaunchActive(target, signal);
      await stdio.start();
      this.assertLaunchActive(target, signal);

      const pid = stdio.pid;
      if (pid === null) {
        throw new Error("Agent Plugin stdio server did not start.");
      }

      stdio.stderr?.on("data", () => undefined);
      this.processTracking.register(
        pid,
        "child",
        `agent-plugin:${target.runtimeName}`,
        {
          taskId: target.taskId,
          taskRunId: target.runId,
          installationId: target.installationId,
          server: target.runtimeName,
        },
        target.taskId,
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
          if (target.connection === connection) target.connection = undefined;
          this.processTracking.unregister(pid, "mcp-closed");
          this.processTracking.kill(pid);
          await Promise.allSettled([httpTransport.close(), stdio.close()]);
        },
      };
      return connection;
    } catch (error) {
      intentionallyClosing = true;
      await Promise.allSettled([stdio.close(), httpTransport.close()]);
      if (!signal.aborted) this.reportFailure(target, error);
      throw error;
    } finally {
      signal.removeEventListener("abort", abortStartup);
    }
  }

  private invalidateConnection(
    target: BridgeTarget,
    connection: BridgeConnection,
    error: unknown,
  ): void {
    if (target.connection === connection) target.connection = undefined;
    this.reportFailure(target, error);
    void connection.close();
  }

  private reportFailure(target: BridgeTarget, error: unknown): void {
    if (!target.active || target.failureReported) return;
    target.failureReported = true;
    target.onFailure(errorMessage(error));
  }
}
