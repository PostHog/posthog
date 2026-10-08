import type http from "node:http";
import type { ScopedLogger } from "@posthog/di/logger";
import {
  aiGatewayDenialCode,
  aiGatewayRemintReason,
  applyAllowedModels,
  serializeError,
} from "@posthog/shared";
import { collapsePropertyHeadersForAiGateway } from "@posthog/shared/posthog-property-headers";
import {
  type StreamProgress,
  streamBodyToResponse,
} from "../proxy-stream/proxy-stream";
import type {
  GatewayCredential,
  GatewayCredentialSource,
  GatewayRemintReason,
} from "./ports";
import {
  type Body,
  jsonError,
  PROXY_TIMEOUTS,
  readBody,
  responseHeaders,
  strippedRequestHeaders,
} from "./proxy-http";

type GoCredential = Extract<GatewayCredential, { mode: "go" }>;

export type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export interface SessionTarget {
  kind: "session";
  projectId: number;
  legacyGatewayUrl: string;
  headers: Record<string, string>;
}

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

function isSessionHeader(lower: string): boolean {
  return (
    !SESSION_DROPPED_HEADERS.has(lower) &&
    (SESSION_HEADERS.has(lower) ||
      SESSION_HEADER_PREFIXES.some((prefix) => lower.startsWith(prefix)))
  );
}

/** Serves session targets: Go under a per-request credential, else legacy. */
export class GatewaySessionHandler {
  private readonly modes = new WeakMap<SessionTarget, "go" | "legacy">();

  constructor(
    private readonly deps: {
      log: ScopedLogger;
      fetchImpl: FetchLike;
      source: () => GatewayCredentialSource;
      forwardLegacy: (
        url: URL,
        options: RequestInit,
        res: http.ServerResponse,
        abort: AbortController,
      ) => Promise<void>;
    },
  ) {}

  async handle(
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
      this.deps.log.warn(
        "Rejected gateway session request outside the allowlist",
        {
          method: req.method,
        },
      );
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

    const credential: GatewayCredential = await this.deps
      .source()
      .getRoute(target.projectId)
      .catch(() => ({ mode: "legacy", reason: "route_failed" }));
    if (abort.signal.aborted) return;
    this.noteMode(
      target,
      credential.mode === "legacy" ? "legacy" : "go",
      credential.mode === "legacy" ? credential.reason : undefined,
    );
    // Listing models is read-only, so a blocked org still sees the picker.
    if (
      credential.mode === "legacy" ||
      (credential.mode === "blocked" && path === "/v1/models")
    ) {
      this.forwardOnLegacy(
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

    await this.forward(
      target,
      credential,
      {
        path,
        search,
        method,
        headers: this.headers(req, target, credential),
        body,
      },
      res,
      abort,
    );
  }

  private noteMode(
    target: SessionTarget,
    mode: "go" | "legacy",
    reason: string | undefined,
  ): void {
    const previous = this.modes.get(target);
    this.modes.set(target, mode);
    if (previous === undefined || previous === mode) return;
    this.deps.log.info("Gateway session switched gateway", {
      projectId: target.projectId,
      from: previous,
      to: mode,
      reason,
    });
  }

  private headers(
    req: http.IncomingMessage,
    target: SessionTarget,
    credential: GoCredential,
  ): Record<string, string> {
    const forwarded: Record<string, string> = {};
    const stripped = strippedRequestHeaders(req.headers.connection);
    for (const [key, value] of Object.entries(req.headers)) {
      const lower = key.toLowerCase();
      if (
        typeof value === "string" &&
        !stripped.has(lower) &&
        isSessionHeader(lower)
      ) {
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

  private async forward(
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
      withDeadline(PROXY_TIMEOUTS.headersMs, () =>
        this.deps.fetchImpl(
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
      withDeadline(PROXY_TIMEOUTS.bufferedBodyMs, read);

    try {
      let credential = initial;
      let response = await send(credential);
      // Retried only here, before any byte reaches the client.
      const refusal = await remintReason(response, buffered);
      let bufferedBody = refusal.body;
      if (refusal.reason) {
        const source = this.deps.source();
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
          ...responseHeaders(response),
          "content-type": "application/json",
        });
        res.end(JSON.stringify(models));
        return;
      }

      res.writeHead(status, responseHeaders(response));
      if (bufferedBody !== null) {
        res.end(bufferedBody);
      } else {
        await streamBodyToResponse(response.body, res, progress);
      }

      this.deps.log.info("Gateway session forward completed", {
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
        this.deps.log.debug(
          "Upstream fetch aborted after client disconnect",
          context,
        );
      } else {
        this.deps.log.error("Gateway session forward error", {
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

  private forwardOnLegacy(
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
    const stripped = strippedRequestHeaders(req.headers.connection);
    for (const [key, value] of Object.entries(req.headers)) {
      const lower = key.toLowerCase();
      if (stripped.has(lower) || typeof value !== "string") {
        continue;
      }
      headers[lower] = value;
    }
    for (const [key, value] of Object.entries(target.headers)) {
      headers[key.toLowerCase()] = value;
    }
    headers["x-posthog-project-id"] = String(target.projectId);
    void this.deps.forwardLegacy(
      url,
      { method, headers, body, signal: abort.signal },
      res,
      abort,
    );
  }
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
