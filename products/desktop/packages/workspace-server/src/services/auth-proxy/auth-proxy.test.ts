import http from "node:http";
import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AuthProxyService,
  SESSION_MAX_BODY_BYTES,
  SESSION_TIMEOUTS,
} from "./auth-proxy";
import type {
  AuthProxyAuth,
  GatewayCredential,
  GatewayCredentialSource,
} from "./ports";

type AuthMock = {
  authenticatedFetch: ReturnType<typeof vi.fn>;
};

describe("AuthProxyService", () => {
  let authMock: AuthMock;
  let service: AuthProxyService;

  beforeEach(() => {
    authMock = { authenticatedFetch: vi.fn() };
    const loggerMock: RootLogger = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      scope: () => ({
        debug: vi.fn(),
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
      }),
    };
    service = new AuthProxyService(
      authMock as unknown as AuthProxyAuth,
      loggerMock,
    );
  });

  afterEach(async () => {
    await service.stop();
    vi.restoreAllMocks();
  });

  it("forwards requests and returns the upstream body and status", async () => {
    authMock.authenticatedFetch.mockResolvedValue(
      new Response('{"ok":true}', {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const proxyUrl = await service.start("https://gateway.example");
    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(200);
    expect(await res.text()).toBe('{"ok":true}');
    const [url] = authMock.authenticatedFetch.mock.calls[0];
    expect(url).toBe("https://gateway.example/v1/messages");
  });

  it("forwards trusted headers instead of client-supplied values", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example", {
      "X-PostHog-Project-Id": "1",
    });
    await fetch(`${proxyUrl}/v1/messages`, {
      headers: { "X-PostHog-Project-Id": "999" },
    });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    const headers = new Headers(options.headers);
    expect(headers.get("X-PostHog-Project-Id")).toBe("1");
  });

  it("rejects requests that do not include the generated access token", async () => {
    const proxyUrl = await service.start("https://gateway.example");
    const proxyOrigin = new URL(proxyUrl).origin;

    const missingToken = await fetch(`${proxyOrigin}/v1/messages`);
    const invalidToken = await fetch(`${proxyOrigin}/invalid/v1/messages`);

    expect(missingToken.status).toBe(401);
    expect(invalidToken.status).toBe(401);
    expect(authMock.authenticatedFetch).not.toHaveBeenCalled();
  });

  it("strips client body framing headers before forwarding", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example");
    await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    const forwardedHeaderKeys = Object.keys(
      options.headers as Record<string, string>,
    ).map((key) => key.toLowerCase());

    expect(forwardedHeaderKeys).not.toContain("content-length");
    expect(forwardedHeaderKeys).not.toContain("transfer-encoding");
    expect(options.headers["content-type"]).toBe("application/json");
  });

  it("passes a connection-lifetime signal so authenticatedFetch's default timeout does not apply", async () => {
    authMock.authenticatedFetch.mockResolvedValue(new Response("ok"));

    const proxyUrl = await service.start("https://gateway.example");
    await fetch(`${proxyUrl}/v1/messages`, { method: "POST", body: "{}" });

    const [, options] = authMock.authenticatedFetch.mock.calls[0];
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.signal.aborted).toBe(false);
  });

  it("aborts the upstream fetch when the client disconnects mid-stream", async () => {
    let upstreamSignal: AbortSignal | undefined;
    authMock.authenticatedFetch.mockImplementation(
      async (_url: string, options: RequestInit) => {
        upstreamSignal = options.signal ?? undefined;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode("data: one\n\n"));
            // Never closes — simulates an in-flight LLM stream.
          },
        });
        return new Response(stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      },
    );

    const proxyUrl = await service.start("https://gateway.example");
    const clientAbort = new AbortController();
    const res = await fetch(`${proxyUrl}/v1/messages`, {
      signal: clientAbort.signal,
    });
    const reader = res.body?.getReader();
    await reader?.read();

    expect(upstreamSignal?.aborted).toBe(false);
    clientAbort.abort();

    await vi.waitFor(() => {
      expect(upstreamSignal?.aborted).toBe(true);
    });
  });

  it("streams the upstream body through to the client", async () => {
    authMock.authenticatedFetch.mockResolvedValue(
      new Response("data: one\n\ndata: two\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );

    const proxyUrl = await service.start("https://gateway.example");
    const res = await fetch(`${proxyUrl}/v1/messages`);

    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(await res.text()).toBe("data: one\n\ndata: two\n\n");
  });
});

type GoCredential = Extract<GatewayCredential, { mode: "go" }>;

function goCredential(overrides: Partial<GoCredential> = {}): GoCredential {
  return {
    mode: "go",
    gatewayUrl: "https://ai-gateway.us.posthog.com",
    token: "phe_one",
    teamId: 7,
    projectId: 42,
    allowedModels: ["claude-opus-5"],
    productModels: ["claude-opus-5", "gpt-6-sol"],
    ...overrides,
  };
}

describe("AuthProxyService gateway sessions", () => {
  let authFetch: ReturnType<typeof vi.fn>;
  let goFetch: ReturnType<
    typeof vi.fn<(url: string, init: RequestInit) => Promise<Response>>
  >;
  let source: {
    getRoute: ReturnType<typeof vi.fn>;
    remint: ReturnType<typeof vi.fn>;
    fallBack: ReturnType<typeof vi.fn>;
  };
  let logs: unknown[][];
  let service: AuthProxyService;

  beforeEach(() => {
    authFetch = vi.fn();
    goFetch = vi.fn<(url: string, init: RequestInit) => Promise<Response>>();
    logs = [];
    source = {
      getRoute: vi.fn().mockResolvedValue(goCredential()),
      remint: vi.fn().mockResolvedValue(null),
      fallBack: vi.fn(),
    };
    const record =
      (level: string) =>
      (...args: unknown[]) =>
        logs.push([level, ...args]);
    const scoped = {
      debug: record("debug"),
      info: record("info"),
      warn: record("warn"),
      error: record("error"),
    };
    const logger = { ...scoped, scope: () => scoped } as unknown as RootLogger;
    service = new AuthProxyService(
      { authenticatedFetch: authFetch } as AuthProxyAuth,
      logger,
      source as unknown as GatewayCredentialSource,
      goFetch,
    );
  });

  afterEach(async () => {
    await service.stop();
  });

  function callInit(index: number) {
    return goFetch.mock.calls[index]?.[1] as unknown as {
      headers: Record<string, string>;
      body: Buffer;
      redirect: string;
    };
  }

  async function session(projectId = 42): Promise<string> {
    return service.startGatewaySession({
      projectId,
      legacyGatewayUrl: "https://gateway.us.posthog.com/posthog_code",
    });
  }

  it("forwards with the session token through plain fetch, never authenticatedFetch", async () => {
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages?beta=true`, {
      method: "POST",
      headers: {
        authorization: "Bearer posthog-code-auth-proxy",
        "x-api-key": "posthog-code-auth-proxy",
        cookie: "session=abc",
        "content-type": "application/json",
      },
      body: "{}",
    });

    expect(res.status).toBe(200);
    expect(authFetch).not.toHaveBeenCalled();
    const url = goFetch.mock.calls[0]?.[0];
    const init = callInit(0);
    expect(url).toBe("https://ai-gateway.us.posthog.com/v1/messages?beta=true");
    expect(init.redirect).toBe("manual");
    expect(init.headers.authorization).toBe("Bearer phe_one");
    expect(init.headers).not.toHaveProperty("x-api-key");
    expect(init.headers).not.toHaveProperty("cookie");
    expect(init.headers["content-type"]).toBe("application/json");
    expect(Buffer.from(init.body).toString()).toBe("{}");
  });

  it("collapses property headers, trusts only its own team, and drops legacy-only headers", async () => {
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();

    await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      headers: {
        "x-posthog-property-task_id": "t1",
        "x-posthog-property-team_id": "999",
        "x-posthog-property-$ai_session_id": "task-1",
        "X-PostHog-Project-Id": "999",
        "x-posthog-use-bedrock-fallback": "true",
        "x-posthog-flag-bedrock-llm-gateway": "test",
        "x-posthog-privacy-mode": "true",
        "X-PostHog-User": "distinct-1",
        "anthropic-version": "2023-06-01",
        "anthropic-auth-token": "leak",
        "x-stainless-os": "MacOS",
        "x-posthog-service-tier": "priority",
      },
      body: "{}",
    });

    const headers = callInit(0).headers;
    expect(JSON.parse(headers["X-PostHog-Properties"])).toEqual({
      task_id: "t1",
      team_id: 7,
      ai_product: "posthog_code",
    });
    expect(headers["X-PostHog-Session-Id"]).toBe("task-1");
    expect(headers["x-posthog-user"]).toBe("distinct-1");
    expect(headers["anthropic-version"]).toBe("2023-06-01");
    expect(headers["x-stainless-os"]).toBe("MacOS");
    expect(headers["x-posthog-service-tier"]).toBe("priority");
    for (const dropped of [
      "x-posthog-project-id",
      "x-posthog-use-bedrock-fallback",
      "x-posthog-flag-bedrock-llm-gateway",
      "x-posthog-privacy-mode",
      "anthropic-auth-token",
      "x-posthog-property-task_id",
    ]) {
      expect(headers).not.toHaveProperty(dropped);
    }
  });

  it("strips a leading product slug from the path", async () => {
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();

    await fetch(`${proxyUrl}/posthog_code/v1/chat/completions`, {
      method: "POST",
      body: "{}",
    });

    expect(goFetch.mock.calls[0]?.[0]).toBe(
      "https://ai-gateway.us.posthog.com/v1/chat/completions",
    );
  });

  it.each([
    "/v1/usage/posthog_code",
    "/internal/teams/2/reported-spend",
    "/v1/tokens",
  ])("refuses %s before any fetch", async (path) => {
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}${path}`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(404);
    expect(goFetch).not.toHaveBeenCalled();
  });

  it.each([
    [
      "a 401",
      () => new Response('{"error":"expired"}', { status: 401 }),
      "unauthorized",
    ],
    [
      "a token cap 402 by header",
      () =>
        new Response('{"error":{"message":"admission rejected"}}', {
          status: 402,
          headers: { "X-PostHog-Denial": "token_cap_exceeded" },
        }),
      "token_cap_exceeded",
    ],
    [
      "a token cap 402 by body code",
      () =>
        new Response(
          '{"error":{"code":"token_cap_exceeded","message":"admission rejected"}}',
          {
            status: 402,
          },
        ),
      "token_cap_exceeded",
    ],
  ])("re-mints once and retries after %s", async (_label, refusal, reason) => {
    goFetch
      .mockResolvedValueOnce(refusal())
      .mockResolvedValue(new Response("second"));
    source.remint.mockResolvedValue(goCredential({ token: "phe_two" }));
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: '{"a":1}',
    });

    expect(await res.text()).toBe("second");
    expect(source.remint).toHaveBeenCalledWith(reason, "phe_one", 42);
    expect(source.remint).toHaveBeenCalledTimes(1);
    expect(source.getRoute).toHaveBeenCalledTimes(1);
    expect(goFetch).toHaveBeenCalledTimes(2);
    expect(callInit(1).headers.authorization).toBe("Bearer phe_two");
    expect(Buffer.from(callInit(1).body).toString()).toBe('{"a":1}');
  });

  it("forwards the refusal untouched when the re-mint gives nothing", async () => {
    goFetch.mockResolvedValue(
      new Response('{"error":{"code":"token_cap_exceeded"}}', {
        status: 402,
        headers: { "X-PostHog-Denial": "token_cap_exceeded" },
      }),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(402);
    expect(res.headers.get("x-posthog-denial")).toBe("token_cap_exceeded");
    expect(await res.text()).toBe('{"error":{"code":"token_cap_exceeded"}}');
    expect(goFetch).toHaveBeenCalledTimes(1);
  });

  it("does not re-mint for an org spend refusal", async () => {
    goFetch.mockResolvedValue(
      new Response(
        '{"error":{"code":"credit_bucket_exhausted","message":"limit"}}',
        {
          status: 402,
          headers: {
            "X-PostHog-Denial": "credit_bucket_exhausted:posthog_code_credits",
          },
        },
      ),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(402);
    expect(await res.text()).toContain("credit_bucket_exhausted");
    expect(source.remint).not.toHaveBeenCalled();
  });

  it("never retries once response headers are on the wire", async () => {
    goFetch.mockResolvedValue(
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode("data: one\n\n"));
            controller.error(new Error("upstream reset"));
          },
        }),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      ),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });
    await res.text().catch(() => "");

    expect(res.status).toBe(200);
    expect(goFetch).toHaveBeenCalledTimes(1);
    expect(source.remint).not.toHaveBeenCalled();
  });

  it("filters /v1/models to the product list and marks the pin", async () => {
    goFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          object: "list",
          data: [
            { id: "claude-opus-5" },
            { id: "gpt-6-sol" },
            { id: "internal-model" },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/models`);
    const body = (await res.json()) as { data: unknown[] };

    expect(body.data).toEqual([
      { id: "claude-opus-5", allowed: true, restriction_reason: null },
      {
        id: "gpt-6-sol",
        allowed: false,
        restriction_reason: "paid_plan_required",
      },
    ]);
  });

  it("strips cookies and auth challenges from the response", async () => {
    goFetch.mockResolvedValue(
      new Response("ok", {
        headers: {
          "set-cookie": "a=b",
          "www-authenticate": "Bearer",
          "x-posthog-trace-id": "trace",
        },
      }),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("www-authenticate")).toBeNull();
    expect(res.headers.get("x-posthog-trace-id")).toBe("trace");
  });

  it("strips cookies and auth challenges from a rewritten model list", async () => {
    goFetch.mockResolvedValue(
      new Response('{"data":[]}', {
        headers: { "set-cookie": "a=b", "www-authenticate": "Bearer" },
      }),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/models`);

    expect(res.status).toBe(200);
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("www-authenticate")).toBeNull();
  });

  it("turns an upstream redirect into a 502", async () => {
    goFetch.mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { location: "https://evil.example" },
      }),
    );
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
      redirect: "manual",
    });

    expect(res.status).toBe(502);
    expect(res.headers.get("location")).toBeNull();
  });

  it("refuses a body over the cap with a size error the classifier knows", async () => {
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: Buffer.alloc(SESSION_MAX_BODY_BYTES + 1, 97),
    });

    expect(res.status).toBe(413);
    expect(await res.text()).toContain("request body too large");
    expect(goFetch).not.toHaveBeenCalled();
  });

  it("pins the session timeouts", () => {
    expect(SESSION_TIMEOUTS).toEqual({
      bodyMs: 60_000,
      headersMs: 600_000,
      bufferedBodyMs: 30_000,
    });
  });

  describe("with short timeouts", () => {
    const saved = { ...SESSION_TIMEOUTS };
    afterEach(() => {
      Object.assign(SESSION_TIMEOUTS, saved);
    });

    it("answers 502 and logs an error when Go sends no headers in time", async () => {
      SESSION_TIMEOUTS.headersMs = 100;
      goFetch.mockImplementation(
        (_url, init) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new Error("aborted")),
            );
          }),
      );
      const proxyUrl = await session();

      const res = await fetch(`${proxyUrl}/v1/messages`, {
        method: "POST",
        body: "{}",
      });

      expect(res.status).toBe(502);
      const errors = logs.filter(([level]) => level === "error");
      expect(errors).toEqual([
        [
          "error",
          "Gateway session forward error",
          expect.objectContaining({ timedOut: true }),
        ],
      ]);
      expect(logs.some(([level]) => level === "debug")).toBe(false);
    });

    it.each([
      ["a 401 refusal", "/v1/messages", 401],
      ["the model list", "/v1/models", 200],
    ])(
      "answers 502 when %s body stalls after headers",
      async (_label, path, status) => {
        SESSION_TIMEOUTS.bufferedBodyMs = 100;
        goFetch.mockImplementation(
          async (_url, init) =>
            new Response(
              new ReadableStream<Uint8Array>({
                start(controller) {
                  init.signal?.addEventListener("abort", () =>
                    controller.error(new Error("aborted")),
                  );
                  controller.enqueue(new TextEncoder().encode("{"));
                },
              }),
              { status, headers: { "content-type": "application/json" } },
            ),
        );
        const proxyUrl = await session();

        const res = await fetch(`${proxyUrl}${path}`, {
          method: path === "/v1/models" ? "GET" : "POST",
          body: path === "/v1/models" ? undefined : "{}",
        });

        expect(res.status).toBe(502);
        expect(source.remint).not.toHaveBeenCalled();
        expect(logs).toContainEqual([
          "error",
          "Gateway session forward error",
          expect.objectContaining({ timedOut: true }),
        ]);
      },
    );

    it("keeps streaming past the headers timeout once headers arrive", async () => {
      SESSION_TIMEOUTS.headersMs = 50;
      // Like real fetch, the body errors once the request signal aborts.
      goFetch.mockImplementation(
        async (_url, init) =>
          new Response(
            new ReadableStream<Uint8Array>({
              async start(controller) {
                init.signal?.addEventListener("abort", () =>
                  controller.error(new Error("aborted")),
                );
                controller.enqueue(new TextEncoder().encode("data: one\n\n"));
                await new Promise((resolve) => setTimeout(resolve, 150));
                controller.enqueue(new TextEncoder().encode("data: two\n\n"));
                controller.close();
              },
            }),
            { status: 200, headers: { "content-type": "text/event-stream" } },
          ),
      );
      const proxyUrl = await session();

      const res = await fetch(`${proxyUrl}/v1/messages`, {
        method: "POST",
        body: "{}",
      });

      expect(await res.text()).toBe("data: one\n\ndata: two\n\n");
    });

    it("answers 408 when the request body stalls", async () => {
      SESSION_TIMEOUTS.bodyMs = 100;
      const proxyUrl = new URL(await session());
      const status = await new Promise<number>((resolve, reject) => {
        const req = http.request(
          {
            host: proxyUrl.hostname,
            port: proxyUrl.port,
            path: `${proxyUrl.pathname}/v1/messages`,
            method: "POST",
            headers: { "content-length": "100" },
          },
          (res) => {
            resolve(res.statusCode ?? 0);
            res.resume();
            req.destroy();
          },
        );
        req.on("error", reject);
        req.write("{");
      });

      expect(status).toBe(408);
      expect(goFetch).not.toHaveBeenCalled();
    });
  });

  it.each([
    [401, true],
    [402, false],
  ])(
    "forwards a 401 on the token re-minted after a %s, falling back only for a 401 pair",
    async (firstStatus, fallsBack) => {
      goFetch
        .mockResolvedValueOnce(
          new Response("first", {
            status: firstStatus,
            headers:
              firstStatus === 402
                ? { "X-PostHog-Denial": "token_cap_exceeded" }
                : {},
          }),
        )
        .mockResolvedValueOnce(new Response("second", { status: 401 }));
      source.remint.mockResolvedValue(goCredential({ token: "phe_two" }));
      const proxyUrl = await session();

      const res = await fetch(`${proxyUrl}/v1/messages`, {
        method: "POST",
        body: "{}",
      });

      expect(res.status).toBe(401);
      expect(await res.text()).toBe("second");
      expect(goFetch).toHaveBeenCalledTimes(2);
      expect(source.remint).toHaveBeenCalledTimes(1);
      expect(authFetch).not.toHaveBeenCalled();
      if (fallsBack) {
        expect(source.fallBack).toHaveBeenCalledWith("phe_two", 42);
      } else {
        expect(source.fallBack).not.toHaveBeenCalled();
      }
    },
  );

  it("does not fall back when the re-minted token hits its cap", async () => {
    goFetch
      .mockResolvedValueOnce(new Response("first", { status: 401 }))
      .mockResolvedValueOnce(
        new Response("second", {
          status: 402,
          headers: { "X-PostHog-Denial": "token_cap_exceeded" },
        }),
      );
    source.remint.mockResolvedValue(goCredential({ token: "phe_two" }));
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(402);
    expect(source.fallBack).not.toHaveBeenCalled();
  });

  it("does not fall back when the re-minted token succeeds", async () => {
    goFetch
      .mockResolvedValueOnce(new Response("first", { status: 401 }))
      .mockResolvedValueOnce(new Response("second", { status: 200 }));
    source.remint.mockResolvedValue(goCredential({ token: "phe_two" }));
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(await res.text()).toBe("second");
    expect(source.fallBack).not.toHaveBeenCalled();
  });

  it("binds each project to its own URL and team", async () => {
    goFetch.mockImplementation(async () => new Response("ok"));
    source.getRoute.mockImplementation(async (projectId: number) =>
      goCredential({ teamId: projectId + 1000, projectId }),
    );
    const first = await session(1);
    const second = await session(2);

    expect(first).not.toBe(second);
    await fetch(`${second}/v1/messages`, {
      method: "POST",
      headers: { "X-PostHog-Project-Id": "1" },
      body: "{}",
    });

    expect(source.getRoute).toHaveBeenCalledWith(2);
    const headers = callInit(0).headers;
    expect(JSON.parse(headers["X-PostHog-Properties"]).team_id).toBe(1002);
  });

  it("stays on the legacy gateway when the source falls back mid-session", async () => {
    authFetch.mockResolvedValue(new Response("legacy"));
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();
    await fetch(`${proxyUrl}/v1/messages`, { method: "POST", body: "{}" });
    goFetch.mockClear();
    source.getRoute.mockResolvedValue({
      mode: "legacy",
      reason: "not_rolled_out",
    });

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      headers: {
        authorization: "Bearer posthog-code-auth-proxy",
        "x-api-key": "posthog-code-auth-proxy",
      },
      body: "{}",
    });

    expect(await res.text()).toBe("legacy");
    await fetch(`${proxyUrl}/v1/messages`, { method: "POST", body: "{}" });
    expect(goFetch).not.toHaveBeenCalled();
    const [url, init] = authFetch.mock.calls[0];
    expect(url).toBe("https://gateway.us.posthog.com/posthog_code/v1/messages");
    expect(init.headers["x-posthog-project-id"]).toBe("42");
    expect(init.headers.authorization).toBeUndefined();
    expect(init.headers["x-api-key"]).toBeUndefined();
    const switched = logs.filter(
      ([, message]) => message === "Gateway session switched gateway",
    );
    expect(switched).toEqual([
      [
        "info",
        "Gateway session switched gateway",
        { projectId: 42, from: "go", to: "legacy", reason: "not_rolled_out" },
      ],
    ]);
  });

  it("sends nothing upstream when the client hangs up while a token is minted", async () => {
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();
    let resolveRoute: (credential: GoCredential) => void = () => undefined;
    source.getRoute.mockImplementation(
      () =>
        new Promise<GoCredential>((resolve) => {
          resolveRoute = resolve;
        }),
    );
    const clientAbort = new AbortController();

    const request = fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
      signal: clientAbort.signal,
    }).catch(() => undefined);
    await vi.waitFor(() => expect(source.getRoute).toHaveBeenCalled());
    clientAbort.abort();
    await request;
    await new Promise((resolve) => setTimeout(resolve, 50));
    resolveRoute(goCredential());
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(goFetch).not.toHaveBeenCalled();
  });

  it("replays the mint's usage-limit sentence when the bucket is empty", async () => {
    const proxyUrl = await session();
    source.getRoute.mockResolvedValue({
      mode: "blocked",
      reason: "credit_bucket_exhausted",
      detail: "Your organization has reached its PostHog Desktop usage limit",
    });

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(res.status).toBe(402);
    const body = (await res.json()) as {
      error: { code: string; message: string };
    };
    expect(body.error.code).toBe("credit_bucket_exhausted");
    expect(body.error.message).toBe(
      "Your organization has reached its PostHog Desktop usage limit",
    );
  });

  it("still lists models on the legacy gateway while blocked", async () => {
    authFetch.mockResolvedValue(new Response('{"data":[]}'));
    const proxyUrl = await session();
    source.getRoute.mockResolvedValue({
      mode: "blocked",
      reason: "credit_bucket_exhausted",
      detail: "limit",
    });

    const res = await fetch(`${proxyUrl}/v1/models`);

    expect(res.status).toBe(200);
    expect(authFetch.mock.calls[0][0]).toBe(
      "https://gateway.us.posthog.com/posthog_code/v1/models",
    );
  });

  it("falls back to the legacy gateway when the source fails", async () => {
    authFetch.mockResolvedValue(new Response("legacy"));
    source.getRoute.mockRejectedValue(new Error("boom"));
    const proxyUrl = await session();

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(await res.text()).toBe("legacy");
    expect(goFetch).not.toHaveBeenCalled();
  });

  it("keeps serving a session target after sign-out, on the legacy route", async () => {
    authFetch.mockResolvedValue(new Response("legacy"));
    const proxyUrl = await session();
    source.getRoute.mockResolvedValue({ mode: "legacy", reason: "signed_out" });

    const res = await fetch(`${proxyUrl}/v1/messages`, {
      method: "POST",
      body: "{}",
    });

    expect(await res.text()).toBe("legacy");
    expect(goFetch).not.toHaveBeenCalled();
  });

  it("never logs the path token or the query string of a Go request", async () => {
    goFetch.mockResolvedValue(new Response("ok"));
    const proxyUrl = await session();

    await fetch(`${proxyUrl}/v1/messages?beta=true&secret=q`, {
      method: "POST",
      body: "{}",
    });
    await fetch(`${proxyUrl}/v1/not-allowed`);
    goFetch.mockRejectedValueOnce(new Error("boom"));
    await fetch(`${proxyUrl}/v1/messages?secret=q`, {
      method: "POST",
      body: "{}",
    });

    const text = JSON.stringify(logs);
    expect(logs.length).toBeGreaterThan(0);
    expect(text).not.toContain(new URL(proxyUrl).pathname.slice(1));
    expect(text).not.toContain("secret=q");
  });
});
