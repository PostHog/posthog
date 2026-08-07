import http from "node:http";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable, preDestroy } from "inversify";
import { streamBodyToResponse } from "../proxy-stream/proxy-stream";

interface ProxyTarget {
  runId: string;
  url: string;
  headers: Record<string, string>;
}

export interface AgentPluginHttpProxyRegistration {
  id: string;
  runId: string;
  url: string;
  headers: Record<string, string>;
}

export interface AgentPluginHttpProxy {
  register(registration: AgentPluginHttpProxyRegistration): Promise<string>;
  unregisterRun(runId: string): void;
}

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "proxy-authorization",
  "transfer-encoding",
]);
const SENSITIVE_REDIRECT_HEADERS = new Set([
  "authorization",
  "cookie",
  "proxy-authorization",
]);

function mergeRequestHeaders(
  configured: Record<string, string>,
  incoming: http.IncomingHttpHeaders,
): Headers {
  const headers = new Headers();
  for (const [name, value] of Object.entries(configured)) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      headers.set(name, value);
    }
  }
  for (const [name, value] of Object.entries(incoming)) {
    if (HOP_BY_HOP_HEADERS.has(name.toLowerCase()) || value === undefined) {
      continue;
    }
    headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  return headers;
}

export function headersAfterRedirect(
  headers: Headers,
  configuredHeaderNames: ReadonlySet<string>,
  previousUrl: URL,
  nextUrl: URL,
): Headers {
  const redirectedHeaders = new Headers(headers);
  if (previousUrl.origin === nextUrl.origin) return redirectedHeaders;

  for (const name of configuredHeaderNames) {
    redirectedHeaders.delete(name);
  }
  for (const name of SENSITIVE_REDIRECT_HEADERS) {
    redirectedHeaders.delete(name);
  }
  return redirectedHeaders;
}

function responseHeaders(response: Response): Record<string, string> {
  const headers: Record<string, string> = {};
  response.headers.forEach((value, name) => {
    if (
      name !== "content-encoding" &&
      name !== "content-length" &&
      name !== "transfer-encoding"
    ) {
      headers[name] = value;
    }
  });
  return headers;
}

@injectable()
export class AgentPluginHttpProxyService implements AgentPluginHttpProxy {
  private server: http.Server | null = null;
  private port: number | null = null;
  private startPromise: Promise<void> | null = null;
  private readonly targets = new Map<string, ProxyTarget>();
  private readonly activeRequests = new Map<string, Set<AbortController>>();
  private readonly log: ScopedLogger;

  constructor(@inject(ROOT_LOGGER) logger: RootLogger) {
    this.log = logger.scope("agent-plugin-http-proxy");
  }

  async register(
    registration: AgentPluginHttpProxyRegistration,
  ): Promise<string> {
    await this.start();
    this.targets.set(registration.id, {
      runId: registration.runId,
      url: registration.url,
      headers: registration.headers,
    });
    return `http://127.0.0.1:${this.port}/${encodeURIComponent(registration.id)}`;
  }

  unregisterRun(runId: string): void {
    for (const [id, target] of this.targets) {
      if (target.runId === runId) this.targets.delete(id);
    }
    for (const controller of this.activeRequests.get(runId) ?? []) {
      controller.abort();
    }
    this.activeRequests.delete(runId);
  }

  @preDestroy()
  async stop(): Promise<void> {
    for (const controllers of this.activeRequests.values()) {
      for (const controller of controllers) controller.abort();
    }
    this.activeRequests.clear();
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
        this.log.warn("Agent Plugin MCP proxy request failed", {
          error: error instanceof Error ? error.message : String(error),
        });
        if (!response.headersSent) {
          response.writeHead(502, {
            "x-posthog-agent-plugin-proxy-error": "1",
          });
        }
        response.end("Agent Plugin MCP proxy error");
      });
    });
    this.server = server;
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        server.off("error", reject);
        const address = server.address();
        if (typeof address !== "object" || address === null) {
          reject(new Error("Failed to start Agent Plugin HTTP proxy."));
          return;
        }
        this.port = address.port;
        server.on("error", (error) => {
          this.log.error("Agent Plugin MCP proxy server failed", error);
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
    const [rawId, ...suffixSegments] = incomingUrl.pathname
      .split("/")
      .filter(Boolean);
    const id = rawId ? decodeURIComponent(rawId) : "";
    const target = this.targets.get(id);
    if (!target) {
      response.writeHead(404);
      response.end("Unknown Agent Plugin MCP target");
      return;
    }

    const targetUrl = new URL(target.url);
    const suffix = suffixSegments.join("/");
    if (suffix) {
      targetUrl.pathname = `${targetUrl.pathname.replace(/\/+$/, "")}/${suffix}`;
    }
    for (const [name, value] of incomingUrl.searchParams) {
      targetUrl.searchParams.append(name, value);
    }
    const body = await this.readRequestBody(request);
    const controller = new AbortController();
    const active = this.activeRequests.get(target.runId) ?? new Set();
    active.add(controller);
    this.activeRequests.set(target.runId, active);
    response.on("close", () => {
      if (!response.writableEnded) controller.abort();
    });

    try {
      const incomingHeaderNames = new Set(
        Object.keys(request.headers).map((name) => name.toLowerCase()),
      );
      const configuredHeaderNames = new Set(
        Object.keys(target.headers)
          .map((name) => name.toLowerCase())
          .filter((name) => !incomingHeaderNames.has(name)),
      );
      const upstream = await this.fetchWithRedirects(
        targetUrl,
        {
          method: request.method ?? "GET",
          headers: mergeRequestHeaders(target.headers, request.headers),
          ...(body.length > 0 ? { body: Uint8Array.from(body).buffer } : {}),
          signal: controller.signal,
        },
        configuredHeaderNames,
      );
      response.writeHead(upstream.status, responseHeaders(upstream));
      await streamBodyToResponse(upstream.body, response);
    } catch (error) {
      if (!controller.signal.aborted) {
        this.log.warn("Agent Plugin MCP proxy request failed", {
          target: id,
          error: error instanceof Error ? error.message : String(error),
        });
      }
      if (!response.headersSent) {
        response.writeHead(502, {
          "x-posthog-agent-plugin-proxy-error": "1",
        });
      }
      response.end("Agent Plugin MCP proxy error");
    } finally {
      active.delete(controller);
      if (active.size === 0) this.activeRequests.delete(target.runId);
    }
  }

  private async fetchWithRedirects(
    initialUrl: URL,
    initialOptions: RequestInit,
    configuredHeaderNames: ReadonlySet<string>,
  ): Promise<Response> {
    let url = initialUrl;
    let method = initialOptions.method ?? "GET";
    let body = initialOptions.body;
    let headers = new Headers(initialOptions.headers);

    for (let redirectCount = 0; redirectCount <= 5; redirectCount += 1) {
      const response = await fetch(url, {
        ...initialOptions,
        method,
        headers,
        ...(body !== undefined ? { body } : { body: undefined }),
        redirect: "manual",
      });
      if (![301, 302, 303, 307, 308].includes(response.status)) {
        return response;
      }
      const location = response.headers.get("location");
      if (!location || redirectCount === 5) {
        throw new Error("Agent Plugin MCP redirect could not be followed.");
      }

      const nextUrl = new URL(location, url);
      headers = headersAfterRedirect(
        headers,
        configuredHeaderNames,
        url,
        nextUrl,
      );
      if (
        response.status === 303 ||
        ((response.status === 301 || response.status === 302) &&
          method.toUpperCase() === "POST")
      ) {
        method = "GET";
        body = undefined;
        headers.delete("content-type");
      }
      url = nextUrl;
    }
    throw new Error("Agent Plugin MCP redirect limit exceeded.");
  }

  private readRequestBody(request: http.IncomingMessage): Promise<Buffer> {
    if (request.method === "GET" || request.method === "HEAD") {
      return Promise.resolve(Buffer.alloc(0));
    }
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      request.on("data", (chunk: Buffer) => chunks.push(chunk));
      request.on("end", () => resolve(Buffer.concat(chunks)));
      request.on("error", reject);
    });
  }
}
