import * as crypto from "node:crypto";
import http from "node:http";
import * as net from "node:net";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable, preDestroy } from "inversify";
import { streamBodyToResponse } from "../proxy-stream/proxy-stream";

interface ProxyTarget {
  registrationId: string;
  runId: string;
  installationId: string;
  url: string;
  headers: Record<string, string>;
}

interface ActiveRequest {
  controller: AbortController;
  target: ProxyTarget;
  routeToken: string;
}

export interface AgentPluginHttpProxyRegistration {
  id: string;
  runId: string;
  installationId: string;
  url: string;
  headers: Record<string, string>;
}

export interface AgentPluginHttpProxy {
  register(registration: AgentPluginHttpProxyRegistration): Promise<string>;
  unregisterRun(runId: string): void;
  unregisterInstallation(installationId: string): void;
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
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
const MAX_REDIRECTS = 5;
const MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024;

function isLoopbackHostname(hostname: string): boolean {
  if (hostname === "localhost") return true;
  const ipVersion = net.isIP(hostname);
  if (ipVersion === 4) return hostname.startsWith("127.");
  if (ipVersion === 6) return hostname === "::1";
  return false;
}

function assertAllowedMcpUrl(url: URL): void {
  if (url.username || url.password || url.hash) {
    throw new Error("Agent Plugin MCP URL contains forbidden URL components.");
  }
  if (url.protocol === "https:") return;
  if (url.protocol === "http:" && isLoopbackHostname(url.hostname)) return;
  throw new Error("Agent Plugin MCP URL must use HTTPS unless it is loopback.");
}

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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

@injectable()
export class AgentPluginHttpProxyService implements AgentPluginHttpProxy {
  private server: http.Server | null = null;
  private port: number | null = null;
  private startPromise: Promise<void> | null = null;
  private readonly targets = new Map<string, ProxyTarget>();
  private readonly routeByRegistration = new Map<string, string>();
  private readonly activeRequests = new Set<ActiveRequest>();
  private readonly log: ScopedLogger;

  constructor(@inject(ROOT_LOGGER) logger: RootLogger) {
    this.log = logger.scope("agent-plugin-http-proxy");
  }

  async register(
    registration: AgentPluginHttpProxyRegistration,
  ): Promise<string> {
    const parsedUrl = new URL(registration.url);
    assertAllowedMcpUrl(parsedUrl);
    await this.start();

    const existingRoute = this.routeByRegistration.get(registration.id);
    if (existingRoute) this.unregisterRoute(existingRoute);

    const routeToken = crypto.randomBytes(32).toString("base64url");
    this.targets.set(routeToken, {
      registrationId: registration.id,
      runId: registration.runId,
      installationId: registration.installationId,
      url: parsedUrl.toString(),
      headers: registration.headers,
    });
    this.routeByRegistration.set(registration.id, routeToken);
    return `http://127.0.0.1:${this.port}/${routeToken}`;
  }

  unregisterRun(runId: string): void {
    this.unregisterWhere((target) => target.runId === runId);
  }

  unregisterInstallation(installationId: string): void {
    this.unregisterWhere((target) => target.installationId === installationId);
  }

  @preDestroy()
  async stop(): Promise<void> {
    for (const request of this.activeRequests) request.controller.abort();
    this.activeRequests.clear();
    this.targets.clear();
    this.routeByRegistration.clear();
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

  private unregisterWhere(predicate: (target: ProxyTarget) => boolean): void {
    for (const [routeToken, target] of this.targets) {
      if (predicate(target)) this.unregisterRoute(routeToken);
    }
    for (const request of this.activeRequests) {
      if (predicate(request.target)) request.controller.abort();
    }
  }

  private unregisterRoute(routeToken: string): void {
    const target = this.targets.get(routeToken);
    if (!target) return;
    this.targets.delete(routeToken);
    if (this.routeByRegistration.get(target.registrationId) === routeToken) {
      this.routeByRegistration.delete(target.registrationId);
    }
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
        this.log.warn("Agent Plugin MCP proxy request failed", {
          error: errorMessage(error),
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
    if (request.headers.origin || request.headers["sec-fetch-site"]) {
      response.writeHead(403);
      response.end("Browser requests are not allowed");
      return;
    }

    const incomingUrl = new URL(request.url ?? "/", "http://localhost");
    const [routeToken, ...suffixSegments] = incomingUrl.pathname
      .split("/")
      .filter(Boolean);
    const target = routeToken ? this.targets.get(routeToken) : undefined;
    if (!routeToken || !target) {
      response.writeHead(404);
      response.end("Unknown Agent Plugin MCP target");
      return;
    }

    const controller = new AbortController();
    const activeRequest: ActiveRequest = {
      controller,
      target,
      routeToken,
    };
    this.activeRequests.add(activeRequest);
    response.on("close", () => {
      if (!response.writableEnded) controller.abort();
    });

    try {
      const targetUrl = new URL(target.url);
      const suffix = suffixSegments.join("/");
      if (suffix) {
        targetUrl.pathname = `${targetUrl.pathname.replace(/\/+$/, "")}/${suffix}`;
      }
      for (const [name, value] of incomingUrl.searchParams) {
        targetUrl.searchParams.append(name, value);
      }

      const body = await this.readRequestBody(request, controller.signal);
      if (
        controller.signal.aborted ||
        this.targets.get(routeToken) !== target
      ) {
        throw new Error("Agent Plugin MCP target was removed.");
      }

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
      if (
        controller.signal.aborted ||
        this.targets.get(routeToken) !== target
      ) {
        throw new Error("Agent Plugin MCP target was removed.");
      }
      response.writeHead(upstream.status, responseHeaders(upstream));
      await streamBodyToResponse(upstream.body, response);
    } catch (error) {
      if (!controller.signal.aborted) {
        this.log.warn("Agent Plugin MCP proxy request failed", {
          target: target.registrationId,
          error: errorMessage(error),
        });
      }
      if (!response.headersSent) {
        const status =
          error instanceof RequestBodyTooLargeError
            ? 413
            : controller.signal.aborted
              ? 404
              : 502;
        response.writeHead(status, {
          "x-posthog-agent-plugin-proxy-error": "1",
        });
      }
      response.end(
        error instanceof RequestBodyTooLargeError
          ? "Agent Plugin MCP request body is too large"
          : "Agent Plugin MCP proxy error",
      );
    } finally {
      this.activeRequests.delete(activeRequest);
    }
  }

  private async fetchWithRedirects(
    initialUrl: URL,
    initialOptions: RequestInit,
    configuredHeaderNames: ReadonlySet<string>,
  ): Promise<Response> {
    assertAllowedMcpUrl(initialUrl);
    const approvedOrigin = initialUrl.origin;
    const visited = new Set<string>();
    let url = initialUrl;
    let method = initialOptions.method ?? "GET";
    let body = initialOptions.body;
    let headers = new Headers(initialOptions.headers);

    for (
      let redirectCount = 0;
      redirectCount <= MAX_REDIRECTS;
      redirectCount += 1
    ) {
      if (visited.has(url.toString())) {
        throw new Error("Agent Plugin MCP redirect loop detected.");
      }
      visited.add(url.toString());

      const response = await fetch(url, {
        ...initialOptions,
        method,
        headers,
        ...(body !== undefined ? { body } : { body: undefined }),
        redirect: "manual",
      });
      if (!REDIRECT_STATUSES.has(response.status)) return response;

      const location = response.headers.get("location");
      if (!location || redirectCount === MAX_REDIRECTS) {
        throw new Error("Agent Plugin MCP redirect limit exceeded.");
      }
      const nextUrl = new URL(location, url);
      assertAllowedMcpUrl(nextUrl);
      if (nextUrl.origin !== approvedOrigin) {
        throw new Error("Agent Plugin MCP cross-origin redirect was blocked.");
      }
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

  private readRequestBody(
    request: http.IncomingMessage,
    signal: AbortSignal,
  ): Promise<Buffer> {
    if (request.method === "GET" || request.method === "HEAD") {
      return Promise.resolve(Buffer.alloc(0));
    }
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      let size = 0;
      const onAbort = (): void => {
        cleanup();
        reject(new Error("Agent Plugin MCP request was aborted."));
      };
      const onData = (chunk: Buffer): void => {
        size += chunk.length;
        if (size > MAX_REQUEST_BODY_BYTES) {
          cleanup();
          reject(new RequestBodyTooLargeError());
          return;
        }
        chunks.push(chunk);
      };
      const onEnd = (): void => {
        cleanup();
        resolve(Buffer.concat(chunks));
      };
      const onError = (error: Error): void => {
        cleanup();
        reject(error);
      };
      const cleanup = (): void => {
        signal.removeEventListener("abort", onAbort);
        request.off("data", onData);
        request.off("end", onEnd);
        request.off("error", onError);
      };

      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener("abort", onAbort, { once: true });
      request.on("data", onData);
      request.on("end", onEnd);
      request.on("error", onError);
    });
  }
}

class RequestBodyTooLargeError extends Error {
  constructor() {
    super("Agent Plugin MCP request body is too large.");
  }
}
