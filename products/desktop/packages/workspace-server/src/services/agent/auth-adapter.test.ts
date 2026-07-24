import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.hoisted(() => vi.fn());

vi.mock("@posthog/agent/posthog-api", () => ({
  getLlmGatewayUrl: vi.fn(() => "https://gateway.example.com"),
}));

vi.stubGlobal("fetch", mockFetch);

import { AgentAuthAdapter } from "./auth-adapter";

const baseCredentials = {
  apiHost: "https://app.posthog.com",
  projectId: 1,
};

function createDependencies() {
  return {
    authService: {
      getValidAccessToken: vi.fn().mockResolvedValue({
        accessToken: "test-access-token",
        apiHost: "https://app.posthog.com",
      }),
      refreshAccessToken: vi.fn().mockResolvedValue({
        accessToken: "fresh-access-token",
        apiHost: "https://app.posthog.com",
      }),
      getState: vi.fn((): { currentProjectId: number | null } => ({
        currentProjectId: 1,
      })),
      authenticatedFetch: vi
        .fn()
        .mockImplementation(
          async (
            fetchImpl: typeof fetch,
            input: string | Request,
            init?: RequestInit,
          ) => fetchImpl(input, init),
        ),
    },
    authProxy: {
      start: vi.fn().mockResolvedValue("http://127.0.0.1:9999"),
    },
    mcpProxy: {
      start: vi.fn().mockResolvedValue(undefined),
      register: vi
        .fn()
        .mockImplementation(
          (id: string) => `http://127.0.0.1:9998/${encodeURIComponent(id)}`,
        ),
    },
    loggerFactory: {
      scope: () => ({
        info: vi.fn(),
        error: vi.fn(),
        warn: vi.fn(),
        debug: vi.fn(),
      }),
    },
  };
}

describe("AgentAuthAdapter", () => {
  let adapter: AgentAuthAdapter;
  let deps: ReturnType<typeof createDependencies>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: [] }),
    });

    deps = createDependencies();
    adapter = new AgentAuthAdapter(
      deps.authService as never,
      deps.authProxy as never,
      deps.mcpProxy as never,
      deps.loggerFactory as never,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("getCurrentCredentials", () => {
    it("returns the auth host and selected project", async () => {
      deps.authService.getState.mockReturnValue({ currentProjectId: 42 });

      await expect(adapter.getCurrentCredentials()).resolves.toEqual({
        apiHost: "https://app.posthog.com",
        projectId: 42,
      });
    });

    it("returns null when no project is selected", async () => {
      deps.authService.getState.mockReturnValue({ currentProjectId: null });

      await expect(adapter.getCurrentCredentials()).resolves.toBeNull();
    });
  });

  it("builds the default PostHog MCP server routed through the local proxy", async () => {
    const { servers } = await adapter.buildMcpServers(baseCredentials);

    expect(deps.mcpProxy.register).toHaveBeenCalledWith(
      "posthog",
      "https://mcp.posthog.com/mcp",
    );
    expect(servers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "posthog",
          type: "http",
          url: "http://127.0.0.1:9998/posthog",
          headers: expect.not.arrayContaining([
            expect.objectContaining({ name: "Authorization" }),
          ]),
        }),
      ]),
    );
  });

  it("identifies as the posthog-code consumer so the MCP server emits UI-app metadata", async () => {
    const { servers } = await adapter.buildMcpServers(baseCredentials);

    const posthogServer = servers.find((s) => s.name === "posthog");
    expect(posthogServer).toBeDefined();
    expect(posthogServer?.headers).toEqual(
      expect.arrayContaining([
        { name: "x-posthog-mcp-consumer", value: "posthog-code" },
      ]),
    );
  });

  it("routes authenticated installed MCP servers through the proxy URL", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          results: [
            {
              id: "inst-2",
              url: "https://remote-mcp.example.com",
              proxy_url: "https://proxy.posthog.com/inst-2/",
              name: "secure-server",
              display_name: "Secure Server",
              auth_type: "oauth",
              is_enabled: true,
              pending_oauth: false,
              needs_reauth: false,
            },
          ],
        }),
    });

    const { servers } = await adapter.buildMcpServers(baseCredentials);

    expect(deps.mcpProxy.register).toHaveBeenCalledWith(
      "installation-inst-2",
      "https://proxy.posthog.com/inst-2/",
    );
    expect(servers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "secure-server",
          url: "http://127.0.0.1:9998/installation-inst-2",
          headers: [],
        }),
      ]),
    );
  });

  it("fetches tool approval states for installations", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            results: [
              {
                id: "inst-3",
                url: "https://tools.example.com",
                proxy_url: "https://proxy.posthog.com/inst-3/",
                name: "tool-server",
                display_name: "Tool Server",
                auth_type: "oauth",
                is_enabled: true,
                pending_oauth: false,
                needs_reauth: false,
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            results: [
              { tool_name: "read_data", approval_state: "approved" },
              { tool_name: "write_data", approval_state: "do_not_use" },
              { tool_name: "query", approval_state: "needs_approval" },
            ],
          }),
      });

    const { toolApprovals, toolInstallations } =
      await adapter.buildMcpServers(baseCredentials);

    expect(toolApprovals).toEqual({
      "mcp__tool-server__read_data": "approved",
      "mcp__tool-server__write_data": "do_not_use",
      "mcp__tool-server__query": "needs_approval",
    });
    expect(toolInstallations["mcp__tool-server__read_data"]).toEqual({
      installationId: "inst-3",
      toolName: "read_data",
    });
  });

  it("returns empty approvals when tool fetch fails", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            results: [
              {
                id: "inst-4",
                url: "https://broken.example.com",
                proxy_url: "https://proxy.posthog.com/inst-4/",
                name: "broken-server",
                display_name: "Broken Server",
                auth_type: "oauth",
                is_enabled: true,
                pending_oauth: false,
                needs_reauth: false,
              },
            ],
          }),
      })
      .mockResolvedValueOnce({ ok: false, status: 500 });

    const { toolApprovals } = await adapter.buildMcpServers(baseCredentials);

    expect(toolApprovals).toEqual({});
  });

  it("configures environment using the gateway proxy and current token", async () => {
    const pathBefore = process.env.PATH;

    await adapter.configureProcessEnv({
      credentials: baseCredentials,
      proxyUrl: "http://127.0.0.1:9999",
      claudeCliPath: "/mock/claude-cli.js",
    });

    expect(process.env.POSTHOG_API_KEY).toBe("test-access-token");
    expect(process.env.POSTHOG_AUTH_HEADER).toBe("Bearer test-access-token");
    expect(process.env.LLM_GATEWAY_URL).toBe("http://127.0.0.1:9999");
    expect(process.env.CLAUDE_CODE_EXECUTABLE).toBe("/mock/claude-cli.js");
    expect(process.env.POSTHOG_PROJECT_ID).toBe("1");
    // The node-shim era prepended a shim dir here; PATH must stay untouched.
    expect(process.env.PATH).toBe(pathBefore);
  });

  it.each([
    { rtkEnabled: false, expected: "0" },
    { rtkEnabled: true, expected: undefined },
    { rtkEnabled: undefined, expected: undefined },
  ])(
    "pins POSTHOG_RTK for rtkEnabled=$rtkEnabled",
    async ({ rtkEnabled, expected }) => {
      // A stale value from a previous session must not leak into an
      // enabled/default session — the enabled path deletes, not skips.
      process.env.POSTHOG_RTK = "0";

      await adapter.configureProcessEnv({
        credentials: baseCredentials,
        proxyUrl: "http://127.0.0.1:9999",
        claudeCliPath: "/mock/claude-cli.js",
        rtkEnabled,
      });

      expect(process.env.POSTHOG_RTK).toBe(expected);
    },
  );
});
