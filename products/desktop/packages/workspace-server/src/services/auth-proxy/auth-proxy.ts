import { randomBytes } from "node:crypto";
import http from "node:http";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { serializeError } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { hopByHop } from "../proxy-stream/hop-by-hop";
import {
  type StreamProgress,
  streamBodyToResponse,
} from "../proxy-stream/proxy-stream";
import { AUTH_PROXY_AUTH } from "./identifiers";
import type { AuthProxyAuth } from "./ports";

type Body = Buffer<ArrayBuffer>;

const STRIPPED_REQUEST_HEADERS = new Set([
  "authorization",
  "x-api-key",
  "api-key",
  "anthropic-auth-token",
  "proxy-authorization",
  "content-length",
  "transfer-encoding",
  "cookie",
]);

const STRIPPED_RESPONSE_HEADERS = new Set([
  "transfer-encoding",
  "content-encoding",
  "content-length",
  "set-cookie",
  "www-authenticate",
]);

export const MAX_BODY_BYTES = 16 * 1024 * 1024;
export const PROXY_TIMEOUTS = {
  bodyMs: 60_000,
  // Non-streaming calls can run for minutes before the first byte, so this
  // only catches a wedged connection.
  headersMs: 10 * 60_000,
};

@injectable()
export class AuthProxyService {
  private server: http.Server | null = null;
  private port: number | null = null;
  private listenPromise: Promise<void> | null = null;
  private readonly targetByToken = new Map<
    string,
    { gatewayUrl: string; headers: Record<string, string> }
  >();
  private readonly tokenByTarget = new Map<string, string>();
  private readonly log: ScopedLogger;

  constructor(
    @inject(AUTH_PROXY_AUTH)
    private readonly auth: AuthProxyAuth,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("auth-proxy");
  }

  async start(
    gatewayUrl: string,
    headers: Record<string, string> = {},
  ): Promise<string> {
    const targetKey = JSON.stringify([
      gatewayUrl,
      Object.entries(headers).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ]);
    let token = this.tokenByTarget.get(targetKey);
    if (!token) {
      token = randomBytes(32).toString("base64url");
      this.tokenByTarget.set(targetKey, token);
      this.targetByToken.set(token, { gatewayUrl, headers: { ...headers } });
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
        this.targetByToken.clear();
        this.tokenByTarget.clear();
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
    const target = token ? this.targetByToken.get(token) : undefined;
    if (!target) {
      res.writeHead(401);
      res.end("Unauthorized");
      return;
    }

    const base = target.gatewayUrl.endsWith("/")
      ? target.gatewayUrl
      : `${target.gatewayUrl}/`;
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
      });
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    const headers: Record<string, string> = {};
    const requestHopByHop = hopByHop(req.headers.connection);
    for (const [key, value] of Object.entries(req.headers)) {
      const name = key.toLowerCase();
      if (
        name === "host" ||
        requestHopByHop.has(name) ||
        STRIPPED_REQUEST_HEADERS.has(name)
      ) {
        continue;
      }
      if (typeof value === "string") {
        headers[key] = value;
      }
    }
    const trustedHeaderNames = new Set(
      Object.keys(target.headers).map((key) => key.toLowerCase()),
    );
    for (const key of Object.keys(headers)) {
      if (trustedHeaderNames.has(key.toLowerCase())) {
        delete headers[key];
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
      headers: { ...headers, ...target.headers },
      signal: abort.signal,
    };

    if (req.method !== "GET" && req.method !== "HEAD") {
      void readBody(req).then((body) => {
        if (typeof body === "string") {
          this.log.warn("Auth proxy refused a request body", {
            method: req.method,
            reason: body,
          });
        }
        if (body === "too_large") {
          // Worded to match the "request body too large" size-error pattern.
          jsonError(
            res,
            413,
            { type: "request_too_large", message: "request body too large" },
            { connection: "close" },
          );
          return;
        }
        if (body === "timeout" || body === "aborted") {
          jsonError(
            res,
            408,
            { type: "timeout_error", message: "request body not received" },
            { connection: "close" },
          );
          return;
        }
        fetchOptions.body = body;
        void this.forwardRequest(targetUrl, fetchOptions, res, abort);
      });
    } else {
      void this.forwardRequest(targetUrl, fetchOptions, res, abort);
    }
  }

  private async forwardRequest(
    target: URL,
    options: RequestInit,
    res: http.ServerResponse,
    abort: AbortController,
  ): Promise<void> {
    if (abort.signal.aborted) return;
    const startedAt = Date.now();
    const progress: StreamProgress = { bytesWritten: 0 };
    // Logged without the query string, which may carry request detail.
    const url = `${target.origin}${target.pathname}`;
    let status = 0;
    let timedOut = false;
    try {
      const timer = setTimeout(() => {
        timedOut = true;
        abort.abort();
      }, PROXY_TIMEOUTS.headersMs);
      let response: Response;
      try {
        response = await this.auth.authenticatedFetch(target.toString(), {
          ...options,
          redirect: "manual",
        });
      } finally {
        clearTimeout(timer);
      }
      status = response.status;

      if (status >= 300 && status < 400) {
        void response.body?.cancel().catch(() => {});
        this.log.warn("Auth proxy refused an upstream redirect", {
          url,
          method: options.method,
          status,
        });
        jsonError(res, 502, {
          type: "api_error",
          message: "Unexpected redirect from the PostHog gateway",
        });
        return;
      }

      const responseHeaders: Record<string, string> = {};
      const responseHopByHop = hopByHop(response.headers.get("connection"));
      response.headers.forEach((value: string, key: string) => {
        const name = key.toLowerCase();
        if (STRIPPED_RESPONSE_HEADERS.has(name) || responseHopByHop.has(name))
          return;
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
      if (timedOut) {
        this.log.warn("Auth proxy upstream sent no response headers in time", {
          url,
          method: options.method,
          durationMs: Date.now() - startedAt,
        });
        jsonError(res, 504, {
          type: "timeout_error",
          message: "PostHog gateway did not respond",
        });
        return;
      }
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

function jsonError(
  res: http.ServerResponse,
  status: number,
  error: Record<string, string>,
  extraHeaders: Record<string, string> = {},
): void {
  if (res.headersSent) {
    res.end();
    return;
  }
  res.writeHead(status, {
    "content-type": "application/json",
    ...extraHeaders,
  });
  res.end(JSON.stringify({ error }));
}

function readBody(
  req: http.IncomingMessage,
): Promise<Body | "too_large" | "timeout" | "aborted"> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    const finish = (result: Body | "too_large" | "timeout" | "aborted") => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.off("data", onData);
      // Drain the rest so the socket can carry the error response.
      if (typeof result === "string") req.resume();
      resolve(result);
    };
    const timer = setTimeout(() => finish("timeout"), PROXY_TIMEOUTS.bodyMs);
    const onData = (chunk: Buffer) => {
      size += chunk.byteLength;
      if (size > MAX_BODY_BYTES) {
        finish("too_large");
        return;
      }
      chunks.push(chunk);
    };
    req.on("data", onData);
    req.on("end", () => finish(Buffer.concat(chunks)));
    req.on("error", () => finish("aborted"));
    req.on("aborted", () => finish("aborted"));
  });
}
