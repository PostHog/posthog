import http from "node:http";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable, preDestroy } from "inversify";
import { streamBodyToResponse } from "../proxy-stream/proxy-stream";
import { MCP_PROXY_AUTH } from "./identifiers";
import type { McpProxyAuth } from "./ports";

function truncateRequestBody(body: RequestInit["body"]): string | undefined {
  if (body == null) return undefined;
  if (typeof body === "string") return body.slice(0, 2000);
  if (body instanceof Buffer) return body.toString("utf8").slice(0, 2000);
  if (body instanceof Uint8Array) {
    return Buffer.from(body).toString("utf8").slice(0, 2000);
  }
  return `[${body.constructor.name}]`;
}

/**
 * Local HTTP proxy for MCP servers. Allows routing MCP requests through a
 * stable loopback URL while injecting a fresh access token on every forwarded
 * request. MCP transports bake their headers at construction time, so without
 * this proxy we would either need to tear the transport down on every token
 * rotation (expensive, racy) or leave it serving stale tokens.
 *
 * The proxy only listens on 127.0.0.1 and strips inbound Authorization headers
 * before forwarding, but any local process can still use it to issue requests
 * on the user's behalf — acceptable for a single-user desktop app.
 */
@injectable()
export class McpProxyService {
  private server: http.Server | null = null;
  private port: number | null = null;
  private startPromise: Promise<void> | null = null;
  private targets = new Map<string, string>();

  private readonly log: ScopedLogger;

  constructor(
    @inject(MCP_PROXY_AUTH)
    private readonly auth: McpProxyAuth,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("mcp-proxy");
  }

  async start(): Promise<void> {
    if (this.server && this.port) return;
    if (this.startPromise) return this.startPromise;
    this.startPromise = this.doStart().catch((err) => {
      this.startPromise = null;
      throw err;
    });
    return this.startPromise;
  }

  private async doStart(): Promise<void> {
    const server = http.createServer((req, res) => {
      this.handleRequest(req, res);
    });
    this.server = server;

    await new Promise<void>((resolve, reject) => {
      server.listen(0, "127.0.0.1", () => {
        const addr = server.address();
        if (typeof addr === "object" && addr) {
          this.port = addr.port;
          this.log.info("MCP proxy started", { port: this.port });
          resolve();
        } else {
          reject(new Error("Failed to get proxy address"));
        }
      });

      server.on("error", (err) => {
        this.log.error("MCP proxy server error", err);
        reject(err);
      });
    });
  }

  /**
   * Register a target URL under a stable ID. Returns the loopback URL that
   * should be passed to the MCP transport. Subsequent registrations with the
   * same ID overwrite the target.
   */
  register(id: string, targetUrl: string): string {
    if (!this.port) {
      throw new Error("MCP proxy not started");
    }
    this.targets.set(id, targetUrl);
    return `http://127.0.0.1:${this.port}/${encodeURIComponent(id)}`;
  }

  @preDestroy()
  async stop(): Promise<void> {
    if (!this.server) return;
    const server = this.server;
    await new Promise<void>((resolve) => {
      server.close(() => {
        this.log.info("MCP proxy stopped");
        resolve();
      });
    });
    this.server = null;
    this.port = null;
    this.startPromise = null;
    this.targets.clear();
  }

  private handleRequest(
    req: http.IncomingMessage,
    res: http.ServerResponse,
  ): void {
    const incoming = new URL(req.url ?? "/", "http://placeholder");
    const segments = incoming.pathname.split("/").filter(Boolean);
    const [rawId, ...rest] = segments;
    const id = rawId ? decodeURIComponent(rawId) : "";
    const target = this.targets.get(id);

    if (!target) {
      // MCP clients probe RFC 8414 OAuth discovery at the proxy root before
      // falling back to direct auth; a quiet 404 is the expected answer.
      if (id === ".well-known") {
        this.log.debug("MCP proxy OAuth discovery probe", { url: req.url });
      } else {
        this.log.warn("Unknown MCP proxy target", { id, url: req.url });
      }
      res.writeHead(404);
      res.end("Unknown target");
      return;
    }

    const suffix = rest.join("/");
    const targetBase = target.replace(/\/+$/, "");
    const targetUrl =
      (suffix ? `${targetBase}/${suffix}` : targetBase) + incoming.search;

    const strippedHeaders = new Set([
      "authorization",
      "proxy-authorization",
      "content-length",
      "transfer-encoding",
    ]);
    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      if (
        key === "host" ||
        key === "connection" ||
        strippedHeaders.has(key.toLowerCase())
      ) {
        continue;
      }
      if (typeof value === "string") {
        headers[key] = value;
      }
    }

    // The client connection governs the request lifetime. An explicit signal
    // also opts out of authenticatedFetch's default timeout, which would
    // abort long-running MCP tool calls that outlive it.
    const abort = new AbortController();
    res.on("close", () => {
      if (!res.writableEnded) {
        abort.abort();
      }
    });

    const fetchOptions: RequestInit = {
      method: req.method ?? "GET",
      headers,
      signal: abort.signal,
    };

    if (req.method !== "GET" && req.method !== "HEAD") {
      const chunks: Buffer[] = [];
      req.on("data", (chunk: Buffer) => chunks.push(chunk));
      req.on("end", () => {
        fetchOptions.body = Buffer.concat(chunks);
        this.forwardRequest(id, targetUrl, fetchOptions, res);
      });
    } else {
      this.forwardRequest(id, targetUrl, fetchOptions, res);
    }
  }

  private async forwardRequest(
    id: string,
    url: string,
    options: RequestInit,
    res: http.ServerResponse,
  ): Promise<void> {
    this.log.debug("MCP proxy forwarding request", {
      id,
      url,
      method: options.method,
      requestBody: truncateRequestBody(options.body),
    });
    try {
      let response = await this.auth.authenticatedFetch(url, options);

      // MCP servers return HTTP 200 with auth failures encoded in the JSON-RPC
      // body, so authenticatedFetch's 401/403 retry never kicks in. Detect the
      // known error shape and retry once with a force-refreshed token.
      const contentType = response.headers.get("content-type") ?? "";
      const isSse = contentType.includes("text/event-stream");

      if (!isSse) {
        const buf = Buffer.from(await response.arrayBuffer());
        const bodyText = buf.toString("utf8");

        if (this.isAuthErrorBody(bodyText, response.status)) {
          this.log.warn("MCP auth failure — refreshing token and retrying", {
            id,
            url,
            method: options.method,
            requestBody: truncateRequestBody(options.body),
            status: response.status,
          });
          await this.auth.refreshAccessToken();
          response = await this.auth.authenticatedFetch(url, options);
          const retryContentType = response.headers.get("content-type") ?? "";
          if (!retryContentType.includes("text/event-stream")) {
            const retryBuf = Buffer.from(await response.arrayBuffer());
            this.writeBufferedResponse(response, retryBuf, res);
            return;
          }
          await this.writeStreamingResponse(response, res);
          return;
        }

        if (/"isError"\s*:\s*true/.test(bodyText) || response.status >= 400) {
          const details = {
            id,
            url,
            method: options.method,
            status: response.status,
            requestBody: truncateRequestBody(options.body),
            responseHeaders: Object.fromEntries(response.headers.entries()),
            body: bodyText.slice(0, 2000),
          };
          // Streamable-HTTP servers MAY answer the client's GET (SSE listen)
          // with 405, and OAuth discovery probes 4xx on servers without OAuth.
          // Both are expected client behavior, not failures worth a warn.
          const expectedProbeRejection =
            response.status < 500 &&
            ((options.method === "GET" && response.status === 405) ||
              url.includes("/.well-known/"));
          if (response.status >= 500) {
            this.log.error("MCP proxy server error", details);
          } else if (expectedProbeRejection) {
            this.log.debug("MCP proxy probe rejected upstream", details);
          } else {
            this.log.warn("MCP proxy non-OK body", details);
          }
        }

        this.writeBufferedResponse(response, buf, res);
        return;
      }

      await this.writeStreamingResponse(response, res);
    } catch (err) {
      if (options.signal?.aborted) {
        this.log.debug("Upstream fetch aborted after client disconnect", {
          id,
          url,
          method: options.method,
        });
      } else {
        this.log.error("MCP proxy forward error", {
          id,
          url,
          method: options.method,
          requestBody: truncateRequestBody(options.body),
          err,
        });
      }
      if (!res.headersSent) {
        res.writeHead(502);
      }
      res.end("Proxy error");
    }
  }

  private isAuthErrorBody(bodyText: string, status: number): boolean {
    if (
      bodyText.includes('"authentication_failed"') ||
      bodyText.includes('"authentication_error"')
    ) {
      return true;
    }
    if (status < 400) return false;
    return (
      bodyText.includes("Invalid API key") ||
      bodyText.includes("Authentication failed")
    );
  }

  private buildResponseHeaders(response: Response): Record<string, string> {
    const stripHeaders = new Set([
      "transfer-encoding",
      "content-encoding",
      "content-length",
    ]);
    const headers: Record<string, string> = {};
    response.headers.forEach((value: string, key: string) => {
      if (stripHeaders.has(key)) return;
      headers[key] = value;
    });
    return headers;
  }

  private writeBufferedResponse(
    response: Response,
    buf: Buffer,
    res: http.ServerResponse,
  ): void {
    res.writeHead(response.status, this.buildResponseHeaders(response));
    res.end(buf);
  }

  private async writeStreamingResponse(
    response: Response,
    res: http.ServerResponse,
  ): Promise<void> {
    res.writeHead(response.status, this.buildResponseHeaders(response));
    await streamBodyToResponse(response.body, res);
  }
}
