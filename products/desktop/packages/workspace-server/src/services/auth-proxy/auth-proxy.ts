import { randomBytes } from "node:crypto";
import http from "node:http";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  aiGatewayDenialCode,
  aiGatewayRemintReason,
  applyAllowedModels,
  serializeError,
} from "@posthog/shared";
import { collapsePropertyHeadersForAiGateway } from "@posthog/shared/posthog-property-headers";
import { inject, injectable, optional } from "inversify";
import {
  type StreamProgress,
  streamBodyToResponse,
} from "../proxy-stream/proxy-stream";
import {
  AUTH_PROXY_AUTH,
  AUTH_PROXY_FETCH,
  GATEWAY_CREDENTIAL_SOURCE,
} from "./identifiers";
import type {
  AuthProxyAuth,
  GatewayCredential,
  GatewayCredentialSource,
  GatewayRemintReason,
} from "./ports";

type GoCredential = Extract<GatewayCredential, { mode: "go" }>;
type FetchLike = (url: string, init: RequestInit) => Promise<Response>;
type Body = Buffer<ArrayBuffer>;

interface LegacyTarget {
  kind: "legacy";
  gatewayUrl: string;
  headers: Record<string, string>;
}

interface SessionTarget {
  kind: "session";
  projectId: number;
  legacyGatewayUrl: string;
  headers: Record<string, string>;
}

type ProxyTarget = LegacyTarget | SessionTarget;

const SESSION_PATHS = new Set([
  "/v1/messages",
  "/v1/messages/count_tokens",
  "/v1/chat/completions",
  "/v1/responses",
  "/v1/models",
]);

const SESSION_HEADERS = new Set([
  "accept",
  "content-type",
  "user-agent",
  "traceparent",
  "tracestate",
  "x-posthog-user",
  "x-posthog-provider",
  "x-posthog-service-tier",
  "x-posthog-trace-id",
  "x-posthog-properties",
  "x-posthog-session-id",
]);
const SESSION_HEADER_PREFIXES = [
  "anthropic-",
  "openai-",
  "x-stainless-",
  "x-posthog-property-",
];
const SESSION_DROPPED_HEADERS = new Set(["anthropic-auth-token"]);

const STRIPPED_REQUEST_HEADERS = new Set([
  "authorization",
  "x-api-key",
  "api-key",
  "anthropic-auth-token",
  "proxy-authorization",
  "content-length",
  "transfer-encoding",
]);

const STRIPPED_RESPONSE_HEADERS = new Set([
  "transfer-encoding",
  "content-encoding",
  "content-length",
]);

const SESSION_STRIPPED_RESPONSE_HEADERS = new Set([
  ...STRIPPED_RESPONSE_HEADERS,
  "connection",
  "keep-alive",
  "set-cookie",
  "www-authenticate",
]);

export const SESSION_MAX_BODY_BYTES = 16 * 1024 * 1024;
export const SESSION_TIMEOUTS = {
  bodyMs: 60_000,
  // Non-streaming calls can run for minutes before the first byte; the ALB in
  // front of Go closes at 300s, so this only catches a wedged connection.
  headersMs: 10 * 60_000,
  // A buffered refusal or model list is small, so a stall here is a fault.
  bufferedBodyMs: 30_000,
};

function isSessionHeader(lower: string): boolean {
  return (
    !SESSION_DROPPED_HEADERS.has(lower) &&
    (SESSION_HEADERS.has(lower) ||
      SESSION_HEADER_PREFIXES.some((prefix) => lower.startsWith(prefix)))
  );
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

@injectable()
export class AuthProxyService {
  private server: http.Server | null = null;
  private port: number | null = null;
  private listenPromise: Promise<void> | null = null;
  private readonly targetByToken = new Map<string, ProxyTarget>();
  private readonly tokenByTarget = new Map<string, string>();
  private readonly sessionModes = new WeakMap<SessionTarget, "go" | "legacy">();
  private readonly log: ScopedLogger;
  private readonly fetchImpl: FetchLike;

  constructor(
    @inject(AUTH_PROXY_AUTH)
    private readonly auth: AuthProxyAuth,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
    @inject(GATEWAY_CREDENTIAL_SOURCE)
    @optional()
    private readonly source?: GatewayCredentialSource,
    @inject(AUTH_PROXY_FETCH)
    @optional()
    fetchImpl?: FetchLike,
  ) {
    this.log = rootLogger.scope("auth-proxy");
    this.fetchImpl = fetchImpl ?? ((url, init) => fetch(url, init));
  }

  async start(
    gatewayUrl: string,
    headers: Record<string, string> = {},
  ): Promise<string> {
    return this.register(["legacy", gatewayUrl], {
      kind: "legacy",
      gatewayUrl,
      headers: { ...headers },
    });
  }

  /**
   * The bearer and gateway URL resolve per request, so a refreshed token never
   * changes the loopback URL the CLI holds.
   */
  async startGatewaySession(input: {
    projectId: number;
    legacyGatewayUrl: string;
    headers?: Record<string, string>;
  }): Promise<string> {
    this.requireSource();
    return this.register(["session", input.projectId, input.legacyGatewayUrl], {
      kind: "session",
      projectId: input.projectId,
      legacyGatewayUrl: input.legacyGatewayUrl,
      headers: { ...(input.headers ?? {}) },
    });
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

  private async register(
    identity: unknown[],
    target: ProxyTarget,
  ): Promise<string> {
    const targetKey = JSON.stringify([
      ...identity,
      Object.entries(target.headers).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ]);
    let token = this.tokenByTarget.get(targetKey);
    if (!token) {
      token = randomBytes(32).toString("base64url");
      this.tokenByTarget.set(targetKey, token);
      this.targetByToken.set(token, target);
    }

    await this.ensureListening();

    return this.getProxyUrl(token);
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

    if (target.kind === "session") {
      void this.handleSessionRequest(
        target,
        match?.[2] ?? "/",
        incomingUrl.search,
        req,
        res,
      );
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
        incoming: req.url,
        target: targetUrl.toString(),
      });
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      if (
        key === "host" ||
        key === "connection" ||
        STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())
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

      res.writeHead(
        response.status,
        responseHeaders(response, STRIPPED_RESPONSE_HEADERS),
      );

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

  private async handleSessionRequest(
    target: SessionTarget,
    subPath: string,
    search: string,
    req: http.IncomingMessage,
    res: http.ServerResponse,
  ): Promise<void> {
    // Attached before any await so a hang-up while the body is read or a
    // token is minted still cancels the upstream call.
    const abort = new AbortController();
    res.on("close", () => {
      if (!res.writableEnded) abort.abort();
    });
    const path = subPath.replace(/^\/posthog_code(?=\/|$)/, "") || "/";
    if (!SESSION_PATHS.has(path)) {
      this.log.warn("Rejected gateway session request outside the allowlist", {
        method: req.method,
      });
      req.resume();
      jsonError(res, 404, { type: "not_found_error", message: "Not found" });
      return;
    }

    const method = req.method ?? "GET";
    let body: Body | undefined;
    if (method !== "GET" && method !== "HEAD") {
      const read = await readBody(req);
      if (read === "too_large") {
        // Worded to match the "request body too large" size-error pattern.
        jsonError(
          res,
          413,
          { type: "request_too_large", message: "request body too large" },
          { connection: "close" },
        );
        return;
      }
      if (read === "timeout" || read === "aborted") {
        jsonError(res, 408, {
          type: "timeout_error",
          message: "request body not received",
        });
        return;
      }
      body = read;
    }

    const credential: GatewayCredential = await this.requireSource()
      .getRoute(target.projectId)
      .catch(() => ({ mode: "legacy", reason: "route_failed" }));
    if (abort.signal.aborted) return;
    this.noteSessionMode(
      target,
      credential.mode === "legacy" ? "legacy" : "go",
      credential.mode === "legacy" ? credential.reason : undefined,
    );
    // Listing models is read-only, so a blocked org still sees the picker.
    if (
      credential.mode === "legacy" ||
      (credential.mode === "blocked" && path === "/v1/models")
    ) {
      this.forwardSessionOnLegacy(
        target,
        { path, search, method, body },
        req,
        res,
        abort,
      );
      return;
    }
    if (credential.mode === "blocked") {
      jsonError(res, 402, {
        type: "billing_error",
        code: credential.reason,
        message: credential.detail,
      });
      return;
    }

    await this.forwardSession(
      target,
      credential,
      {
        path,
        search,
        method,
        headers: this.sessionHeaders(req, target, credential),
        body,
      },
      res,
      abort,
    );
  }

  private noteSessionMode(
    target: SessionTarget,
    mode: "go" | "legacy",
    reason: string | undefined,
  ): void {
    const previous = this.sessionModes.get(target);
    this.sessionModes.set(target, mode);
    if (previous === undefined || previous === mode) return;
    this.log.info("Gateway session switched gateway", {
      projectId: target.projectId,
      from: previous,
      to: mode,
      reason,
    });
  }

  private sessionHeaders(
    req: http.IncomingMessage,
    target: SessionTarget,
    credential: GoCredential,
  ): Record<string, string> {
    const forwarded: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      const lower = key.toLowerCase();
      if (typeof value === "string" && isSessionHeader(lower)) {
        forwarded[lower] = value;
      }
    }
    for (const [key, value] of Object.entries(target.headers)) {
      const lower = key.toLowerCase();
      if (isSessionHeader(lower)) forwarded[lower] = value;
    }
    return collapsePropertyHeadersForAiGateway(forwarded, {
      ai_product: "posthog_code",
      team_id: credential.teamId,
    });
  }

  private async forwardSession(
    target: SessionTarget,
    initial: GoCredential,
    request: {
      path: string;
      search: string;
      method: string;
      headers: Record<string, string>;
      body: Body | undefined;
    },
    res: http.ServerResponse,
    abort: AbortController,
  ): Promise<void> {
    const startedAt = Date.now();
    const progress: StreamProgress = { bytesWritten: 0 };
    let status = 0;
    let timedOut = false;
    const withDeadline = async <T>(
      ms: number,
      run: () => Promise<T>,
    ): Promise<T> => {
      const timer = setTimeout(() => {
        timedOut = true;
        abort.abort();
      }, ms);
      try {
        return await run();
      } finally {
        clearTimeout(timer);
      }
    };
    const send = (credential: GoCredential): Promise<Response> =>
      withDeadline(SESSION_TIMEOUTS.headersMs, () =>
        this.fetchImpl(
          `${credential.gatewayUrl}${request.path}${request.search}`,
          {
            method: request.method,
            headers: {
              ...request.headers,
              authorization: `Bearer ${credential.token}`,
            },
            body: request.body,
            redirect: "manual",
            signal: abort.signal,
          },
        ),
      );
    const buffered = <T>(read: () => Promise<T>): Promise<T> =>
      withDeadline(SESSION_TIMEOUTS.bufferedBodyMs, read);

    try {
      let credential = initial;
      let response = await send(credential);
      // Retried only here, before any byte reaches the client.
      const refusal = await remintReason(response, buffered);
      let bufferedBody = refusal.body;
      if (refusal.reason) {
        const source = this.requireSource();
        const fresh = await source
          .remint(refusal.reason, credential.token, target.projectId)
          .catch(() => null);
        if (fresh?.mode === "go") {
          credential = fresh;
          response = await send(credential);
          bufferedBody = null;
          if (response.status === 401 && refusal.reason === "unauthorized") {
            source.fallBack(credential.token, target.projectId);
          }
        }
      }
      status = response.status;

      if (status >= 300 && status < 400) {
        void response.body?.cancel().catch(() => {});
        jsonError(res, 502, {
          type: "api_error",
          message: "Unexpected redirect from the PostHog gateway",
        });
        return;
      }

      if (request.path === "/v1/models" && response.ok) {
        const body = await buffered(() => response.json());
        const models = applyAllowedModels(body, credential);
        res.writeHead(status, {
          ...responseHeaders(response, SESSION_STRIPPED_RESPONSE_HEADERS),
          "content-type": "application/json",
        });
        res.end(JSON.stringify(models));
        return;
      }

      res.writeHead(
        status,
        responseHeaders(response, SESSION_STRIPPED_RESPONSE_HEADERS),
      );
      if (bufferedBody !== null) {
        res.end(bufferedBody);
      } else {
        await streamBodyToResponse(response.body, res, progress);
      }

      this.log.info("Gateway session forward completed", {
        path: request.path,
        method: request.method,
        status,
        durationMs: Date.now() - startedAt,
        bytesStreamed: progress.bytesWritten,
      });
    } catch (err) {
      const context = {
        path: request.path,
        durationMs: Date.now() - startedAt,
        bytesStreamed: progress.bytesWritten,
      };
      if (abort.signal.aborted && !timedOut) {
        this.log.debug(
          "Upstream fetch aborted after client disconnect",
          context,
        );
      } else {
        this.log.error("Gateway session forward error", {
          ...context,
          method: request.method,
          status,
          headersSent: res.headersSent,
          timedOut,
          errorDetail: serializeError(err),
        });
      }
      if (!res.headersSent) {
        jsonError(res, 502, { type: "api_error", message: "Proxy error" });
        return;
      }
      res.end();
    }
  }

  private forwardSessionOnLegacy(
    target: SessionTarget,
    request: {
      path: string;
      search: string;
      method: string;
      body: Body | undefined;
    },
    req: http.IncomingMessage,
    res: http.ServerResponse,
    abort: AbortController,
  ): void {
    const { path, search, method, body } = request;
    const base = target.legacyGatewayUrl.replace(/\/+$/, "");
    const url = new URL(`${base}${path}${search}`);
    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(req.headers)) {
      const lower = key.toLowerCase();
      if (
        lower === "host" ||
        lower === "connection" ||
        STRIPPED_REQUEST_HEADERS.has(lower) ||
        typeof value !== "string"
      ) {
        continue;
      }
      headers[lower] = value;
    }
    for (const [key, value] of Object.entries(target.headers)) {
      headers[key.toLowerCase()] = value;
    }
    headers["x-posthog-project-id"] = String(target.projectId);
    void this.forwardRequest(
      url.toString(),
      { method, headers, body, signal: abort.signal },
      res,
    );
  }

  private requireSource(): GatewayCredentialSource {
    if (!this.source) {
      throw new Error("Gateway sessions need a credential source");
    }
    return this.source;
  }
}

function responseHeaders(
  response: Response,
  stripped: ReadonlySet<string>,
): Record<string, string> {
  const headers: Record<string, string> = {};
  response.headers.forEach((value: string, key: string) => {
    if (stripped.has(key.toLowerCase())) return;
    headers[key] = value;
  });
  return headers;
}

async function remintReason(
  response: Response,
  buffered: (read: () => Promise<string>) => Promise<string>,
): Promise<{ reason: GatewayRemintReason | null; body: string | null }> {
  if (response.status !== 401 && response.status !== 402) {
    return { reason: null, body: null };
  }
  const body = await buffered(() => response.text());
  const code = aiGatewayDenialCode(
    response.headers.get("x-posthog-denial"),
    body,
  );
  return { reason: aiGatewayRemintReason(response.status, code), body };
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
    const timer = setTimeout(() => finish("timeout"), SESSION_TIMEOUTS.bodyMs);
    const onData = (chunk: Buffer) => {
      size += chunk.byteLength;
      if (size > SESSION_MAX_BODY_BYTES) {
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
