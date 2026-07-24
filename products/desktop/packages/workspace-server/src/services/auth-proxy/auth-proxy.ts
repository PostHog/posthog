import { randomBytes } from "node:crypto";
import http from "node:http";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { serializeError } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  type StreamProgress,
  streamBodyToResponse,
} from "../proxy-stream/proxy-stream";
import { AUTH_PROXY_AUTH } from "./identifiers";
import type { AuthProxyAuth } from "./ports";

@injectable()
export class AuthProxyService {
  private server: http.Server | null = null;
  private port: number | null = null;
  private listenPromise: Promise<void> | null = null;
  private readonly gatewayUrlByToken = new Map<string, string>();
  private readonly tokenByGatewayUrl = new Map<string, string>();
  private readonly log: ScopedLogger;

  constructor(
    @inject(AUTH_PROXY_AUTH)
    private readonly auth: AuthProxyAuth,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("auth-proxy");
  }

  async start(gatewayUrl: string): Promise<string> {
    let token = this.tokenByGatewayUrl.get(gatewayUrl);
    if (!token) {
      token = randomBytes(32).toString("base64url");
      this.tokenByGatewayUrl.set(gatewayUrl, token);
      this.gatewayUrlByToken.set(token, gatewayUrl);
    }

    await this.ensureListening();

    return this.getProxyUrl(token);
  }

  getProxyUrl(token: string): string {
    if (!this.port) {
      throw new Error("Auth proxy not started");
    }
    return `http://127.0.0.1:${this.port}/${token}`;
  }

  isRunning(): boolean {
    return this.server !== null && this.port !== null;
  }

  private ensureListening(): Promise<void> {
    if (this.port) {
      return Promise.resolve();
    }
    if (this.listenPromise) {
      return this.listenPromise;
    }

    this.server = http.createServer((req, res) => {
      this.handleRequest(req, res);
    });
    this.listenPromise = new Promise<void>((resolve, reject) => {
      this.server?.listen(0, "127.0.0.1", () => {
        const address = this.server?.address();
        if (typeof address === "object" && address) {
          this.port = address.port;
          resolve();
          return;
        }
        reject(new Error("Failed to get proxy address"));
      });
      this.server?.on("error", (error) => {
        this.log.error("Auth proxy server error", error);
        reject(error);
      });
    });

    return this.listenPromise;
  }

  async stop(): Promise<void> {
    if (!this.server) return;

    return new Promise<void>((resolve) => {
      this.server?.close(() => {
        this.log.info("Auth proxy stopped");
        this.server = null;
        this.port = null;
        this.listenPromise = null;
        this.gatewayUrlByToken.clear();
        this.tokenByGatewayUrl.clear();
        resolve();
      });
    });
  }

  private handleRequest(
    req: http.IncomingMessage,
    res: http.ServerResponse,
  ): void {
    const incomingUrl = new URL(req.url ?? "/", "http://127.0.0.1");
    const match = incomingUrl.pathname.match(/^\/([^/]+)(\/.*)?$/);
    const token = match?.[1];
    const gatewayUrl = token ? this.gatewayUrlByToken.get(token) : undefined;
    if (!gatewayUrl) {
      res.writeHead(401);
      res.end("Unauthorized");
      return;
    }

    const base = gatewayUrl.endsWith("/") ? gatewayUrl : `${gatewayUrl}/`;
    const targetPath = `${match?.[2] ?? "/"}${incomingUrl.search}`;
    const targetUrl = new URL(targetPath.replace(/^\//, ""), base);

    // Validate that the resolved URL stays within the configured gateway origin
    const gatewayBase = new URL(base);
    const normalizePort = (u: URL): string => {
      if (u.port) return u.port;
      if (u.protocol === "https:") return "443";
      if (u.protocol === "http:") return "80";
      return "";
    };

    const targetPort = normalizePort(targetUrl);
    const gatewayPort = normalizePort(gatewayBase);

    const sameOrigin =
      targetUrl.protocol === gatewayBase.protocol &&
      targetUrl.hostname === gatewayBase.hostname &&
      targetPort === gatewayPort;

    const hasPathTraversal = targetUrl.pathname.includes("..");

    if (!sameOrigin || hasPathTraversal) {
      this.log.warn("Rejected proxy request with invalid target URL", {
        method: req.method,
        incoming: req.url,
        target: targetUrl.toString(),
      });
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    const strippedHeaders = new Set([
      "authorization",
      "x-api-key",
      "api-key",
      "anthropic-auth-token",
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
    // abort streaming LLM responses that outlive it.
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
        this.forwardRequest(targetUrl.toString(), fetchOptions, res);
      });
    } else {
      this.forwardRequest(targetUrl.toString(), fetchOptions, res);
    }
  }

  private async forwardRequest(
    url: string,
    options: RequestInit,
    res: http.ServerResponse,
  ): Promise<void> {
    const startedAt = Date.now();
    const progress: StreamProgress = { bytesWritten: 0 };
    let status = 0;
    try {
      const response = await this.auth.authenticatedFetch(url, options);
      status = response.status;

      const responseHeaders: Record<string, string> = {};
      const stripHeaders = new Set([
        "transfer-encoding",
        "content-encoding",
        "content-length",
      ]);
      response.headers.forEach((value: string, key: string) => {
        if (stripHeaders.has(key)) return;
        responseHeaders[key] = value;
      });

      res.writeHead(response.status, responseHeaders);

      await streamBodyToResponse(response.body, res, progress);

      this.log.info("Auth proxy forward completed", {
        url,
        method: options.method,
        status,
        durationMs: Date.now() - startedAt,
        bytesStreamed: progress.bytesWritten,
      });
    } catch (err) {
      if (options.signal?.aborted) {
        this.log.debug("Upstream fetch aborted after client disconnect", {
          url,
          durationMs: Date.now() - startedAt,
          bytesStreamed: progress.bytesWritten,
        });
      } else {
        this.log.error("Proxy forward error", {
          url,
          method: options.method,
          status,
          headersSent: res.headersSent,
          durationMs: Date.now() - startedAt,
          bytesStreamed: progress.bytesWritten,
          stack: err instanceof Error ? err.stack : undefined,
          errorDetail: serializeError(err),
        });
      }
      if (!res.headersSent) {
        res.writeHead(502);
      }
      res.end("Proxy error");
    }
  }
}
