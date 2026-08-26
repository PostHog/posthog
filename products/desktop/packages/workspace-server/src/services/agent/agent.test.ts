import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// --- Hoisted mocks ---

const mockApp = vi.hoisted(() => ({
  getAppPath: vi.fn(() => "/mock/appPath"),
  isPackaged: false,
  getVersion: vi.fn(() => "0.0.0-test"),
  getPath: vi.fn(() => "/mock/home"),
}));

const mockNewSession = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    sessionId: "test-session-id",
    configOptions: [],
  }),
);
const mockResumeSession = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ configOptions: [] }),
);
const mockPrompt = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ stopReason: "end_turn" }),
);

const mockPrepareContextWiki = vi.hoisted(() => vi.fn());

const mockAcpClient = vi.hoisted(() => ({
  current: undefined as
    | {
        requestPermission: (params: {
          options: Array<{ optionId: string; kind: string; name: string }>;
          toolCall?: {
            toolCallId?: string;
            title?: string;
            _meta?: { codeToolKind?: string };
          };
        }) => Promise<unknown>;
      }
    | undefined,
}));

const mockClientSideConnection = vi.hoisted(() =>
  vi.fn().mockImplementation(function (
    this: Record<string, unknown>,
    clientFactory: (agent: unknown) => typeof mockAcpClient.current,
  ) {
    mockAcpClient.current = clientFactory({});
    this.initialize = vi.fn().mockResolvedValue({});
    this.newSession = mockNewSession;
    this.loadSession = vi.fn().mockResolvedValue({ configOptions: [] });
    this.resumeSession = mockResumeSession;
    this.prompt = mockPrompt;
    this.setSessionConfigOption = vi.fn(
      async ({ value }: { value: string }) => ({
        configOptions: [
          {
            id: "mode",
            name: "Mode",
            description: "Permission mode",
            category: "mode",
            type: "select",
            currentValue: value,
            options: [],
          },
        ],
      }),
    );
  }),
);

const mockAgentRun = vi.hoisted(() =>
  vi.fn().mockImplementation(() =>
    Promise.resolve({
      clientStreams: {
        readable: new ReadableStream(),
        writable: new WritableStream(),
      },
    }),
  ),
);

const mockResumeFromLog = vi.hoisted(() => vi.fn());
const mockFormatConversationForResume = vi.hoisted(() => vi.fn());
const mockHydrateSessionJsonl = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ hasSession: false }),
);

const mockAgentConstructor = vi.hoisted(() =>
  vi.fn().mockImplementation(function (this: Record<string, unknown>) {
    this.run = mockAgentRun;
    this.cleanup = vi.fn().mockResolvedValue(undefined);
    this.getPosthogAPI = vi.fn();
    this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
  }),
);

// --- Module mocks ---

vi.mock("electron", () => ({
  app: mockApp,
}));

vi.mock("@posthog/agent/agent", () => ({
  Agent: mockAgentConstructor,
}));

vi.mock("@agentclientprotocol/sdk", () => ({
  ClientSideConnection: mockClientSideConnection,
  ndJsonStream: vi.fn(),
  PROTOCOL_VERSION: 1,
}));

vi.mock("@posthog/agent", () => ({
  isMcpToolReadOnly: vi.fn(() => false),
  POSTHOG_METHODS: {
    SIDE_QUESTION: "_posthog/side_question",
    REFRESH_SESSION: "_posthog/refresh_session",
  },
}));

vi.mock("@posthog/agent/posthog-api", () => ({
  getLlmGatewayUrl: vi.fn(() => "https://gateway.example.com"),
}));

vi.mock("@posthog/agent/resume", () => ({
  resumeFromLog: mockResumeFromLog,
  formatConversationForResume: mockFormatConversationForResume,
}));

vi.mock("@posthog/agent/gateway-models", () => ({
  DEFAULT_GATEWAY_MODEL: "claude-opus-4-8",
  DEFAULT_CODEX_MODEL: "gpt-5.5",
  fetchGatewayModels: vi.fn().mockResolvedValue([]),
  formatGatewayModelName: vi.fn((model) => model.id),
  getClaudeModelRecency: vi.fn(() => 0),
  getProviderName: vi.fn(),
  isAnthropicModel: vi.fn((model) => model.owned_by === "anthropic"),
  isBlockedModelId: vi.fn().mockReturnValue(false),
  isCloudflareModel: vi.fn((model) => model.owned_by === "cloudflare"),
  isModalModel: vi.fn((model) => model.owned_by === "modal"),
  isOpenAIModel: vi.fn((model) => model.owned_by === "openai"),
  pickAllowedModel: vi.fn((_models, preferredModelId) => preferredModelId),
}));

vi.mock("@posthog/agent/adapters/claude/session/jsonl-hydration", () => ({
  hydrateSessionJsonl: mockHydrateSessionJsonl,
}));

vi.mock("./context-wiki", () => ({
  prepareContextWiki: mockPrepareContextWiki,
}));

vi.mock("node:fs", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs")>();
  return {
    ...original,
    default: {
      ...original,
      existsSync: vi.fn(() => false),
      realpathSync: vi.fn((p: string) => p),
    },
    existsSync: vi.fn(() => false),
    mkdirSync: vi.fn(),
    symlinkSync: vi.fn(),
    realpathSync: vi.fn((p: string) => p),
  };
});

// --- Import after mocks ---
import { fetchGatewayModels } from "@posthog/agent/gateway-models";
import { PRODUCT_ENGINEER_PROMPT } from "@posthog/shared/product-engineer-prompt";
import { RICH_OUTPUT_TAGS_PROMPT } from "@posthog/shared/rich-output-prompt";
import {
  AgentService,
  buildAutoApproveOutcome,
  shouldAutoApprovePermissionRequest,
} from "./agent";
import { AgentServiceEvent } from "./schemas";

// --- Test helpers ---

function createMockDependencies() {
  return {
    processTracking: {
      register: vi.fn(),
      unregister: vi.fn(),
      killByTaskId: vi.fn(),
      getByTaskId: vi.fn(() => []),
      kill: vi.fn(),
    },
    sleepService: {
      acquire: vi.fn(),
      release: vi.fn(),
    },
    fsService: {
      readRepoFile: vi.fn(),
      writeRepoFile: vi.fn(),
    },
    posthogPluginService: {
      getPluginPath: vi.fn(() => "/mock/plugin"),
    },
    agentAuthAdapter: {
      getCurrentCredentials: vi.fn().mockResolvedValue(null),
      gatewayAuthToken: vi.fn().mockResolvedValue("gateway-token"),
      gatewayProjectId: vi.fn().mockReturnValue(1),
      ensureGatewayProxy: vi.fn().mockResolvedValue("http://127.0.0.1:9999"),
      configureProcessEnv: vi.fn().mockResolvedValue(undefined),
      createPosthogConfig: vi.fn((credentials) => ({
        apiUrl: credentials.apiHost,
        getApiKey: vi.fn().mockResolvedValue("test-access-token"),
        refreshApiKey: vi.fn().mockResolvedValue("fresh-access-token"),
        projectId: credentials.projectId,
      })),
      buildMcpServers: vi.fn().mockResolvedValue({
        servers: [
          {
            name: "posthog",
            type: "http",
            url: "https://mcp.posthog.com/mcp",
            headers: [],
          },
        ],
        toolApprovals: {},
        toolInstallations: {},
      }),
    },
    mcpAppsService: {
      setServerConfigs: vi.fn(),
      addServerConfigs: vi.fn(),
      setConfigResolver: vi.fn(),
      handleDiscovery: vi.fn().mockResolvedValue(undefined),
      cleanup: vi.fn().mockResolvedValue(undefined),
      notifyToolInput: vi.fn(),
      notifyToolResult: vi.fn(),
      notifyToolCancelled: vi.fn(),
    },
    powerManager: {
      onResume: vi.fn(() => () => {}),
      preventSleep: vi.fn(() => () => {}),
      hasBuiltInBattery: vi.fn(async () => false),
    },
    bundledResources: {
      resolve: vi.fn((rel: string) => `/mock/appPath/${rel}`),
    },
    appMeta: {
      version: "0.0.0-test",
      isProduction: false,
    },
    storagePaths: {
      appDataPath: "/mock/userData",
      logsPath: "/mock/logs",
    },
    workspaceRepository: {
      getAdditionalDirectories: vi.fn(() => [] as string[]),
      addAdditionalDirectory: vi.fn(),
      removeAdditionalDirectory: vi.fn(),
    },
    workspaceSettings: {
      getWorktreeLocation: () => "/mock/worktrees",
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

const baseSessionParams = {
  taskId: "task-1",
  taskRunId: "run-1",
  repoPath: "/mock/repo",
  apiHost: "https://app.posthog.com",
  projectId: 1,
};

describe("AgentService", () => {
  let service: AgentService;
  let deps: ReturnType<typeof createMockDependencies>;

  beforeEach(() => {
    vi.clearAllMocks();

    deps = createMockDependencies();
    service = new AgentService(
      deps.processTracking as never,
      deps.sleepService as never,
      deps.fsService as never,
      deps.posthogPluginService as never,
      deps.agentAuthAdapter as never,
      deps.mcpAppsService as never,
      deps.powerManager as never,
      deps.bundledResources as never,
      deps.appMeta as never,
      deps.storagePaths as never,
      deps.workspaceRepository as never,
      deps.workspaceSettings as never,
      deps.loggerFactory as never,
    );
    vi.spyOn(service, "emit");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe("context wiki mount", () => {
    const credentials = {
      apiHost: "https://app.posthog.test",
      projectId: 1,
    } as never;
    const mount = {
      path: "/mock/appData/context-wiki/org-1/head1",
      commitsPath: "/api/organizations/org-1/context_layer/commits/",
    };
    const mountContextWiki = () =>
      (
        service as unknown as {
          mountContextWiki: (value: unknown) => Promise<unknown>;
        }
      ).mountContextWiki(credentials);

    const ENV_KEYS = [
      "POSTHOG_API_KEY",
      "POSTHOG_PERSONAL_API_KEY",
      "POSTHOG_CONTEXT_LAYER_PATH",
      "POSTHOG_CONTEXT_LAYER_COMMITS_PATH",
    ];

    beforeEach(() => {
      for (const key of ENV_KEYS) {
        delete process.env[key];
      }
    });

    afterEach(() => {
      for (const key of ENV_KEYS) {
        delete process.env[key];
      }
    });

    // POSTHOG_API_KEY is what the auth sync just wrote, and it is deliberately
    // absent while impersonating — so an impersonation credential must never
    // reach the agent subprocess as a publish token.
    it.each([
      ["the auth sync wrote one", "synced-key", "synced-key"],
      ["the session is impersonated", undefined, undefined],
    ])(
      "exposes a publish token only when %s",
      async (_label, apiKey, expected) => {
        if (apiKey) {
          process.env.POSTHOG_API_KEY = apiKey;
        }
        mockPrepareContextWiki.mockResolvedValueOnce(mount);

        const wiki = await mountContextWiki();

        expect(wiki).toEqual({
          path: mount.path,
          commitsPath: mount.commitsPath,
          personalApiKey: expected,
        });
      },
    );

    // The mount travels per-session precisely because the harness adapters
    // snapshot process.env at spawn time — a global write here would let
    // concurrent session starts leak one session's token into another.
    it("never writes the wiki vars to shared process.env", async () => {
      process.env.POSTHOG_API_KEY = "synced-key";
      mockPrepareContextWiki.mockResolvedValueOnce(mount);

      await mountContextWiki();

      expect(process.env.POSTHOG_CONTEXT_LAYER_PATH).toBeUndefined();
      expect(process.env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH).toBeUndefined();
      expect(process.env.POSTHOG_PERSONAL_API_KEY).toBeUndefined();
    });

    it("threads the mount into agent.run as a per-session value", async () => {
      process.env.POSTHOG_API_KEY = "synced-key";
      mockPrepareContextWiki.mockResolvedValue(mount);

      await service.startSession(baseSessionParams);

      expect(mockAgentRun).toHaveBeenCalledWith(
        "task-1",
        "run-1",
        expect.objectContaining({
          contextWiki: {
            path: mount.path,
            commitsPath: mount.commitsPath,
            personalApiKey: "synced-key",
          },
        }),
      );
    });
  });

  it("includes Modal models in Claude preview options", async () => {
    vi.mocked(fetchGatewayModels).mockResolvedValueOnce([
      {
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      },
      {
        id: "moonshotai/kimi-k3",
        owned_by: "modal",
        context_window: 262_144,
        supports_streaming: true,
        supports_vision: false,
        allowed: true,
      },
    ]);

    const options = await service.getPreviewConfigOptions(
      "https://us.posthog.com",
      "claude",
    );

    expect(fetchGatewayModels).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 1 }),
    );
    const modelOption = options.find((option) => option.id === "model");
    expect(modelOption).toMatchObject({
      type: "select",
      options: expect.arrayContaining([
        expect.objectContaining({ value: "moonshotai/kimi-k3" }),
      ]),
    });
  });

  describe("mcp-apps config resolver", () => {
    function registeredResolver(): (serverName: string) => Promise<void> {
      const call = deps.mcpAppsService.setConfigResolver.mock.calls[0];
      expect(call).toBeDefined();
      return call[0];
    }

    it("registers server configs from the current credentials", async () => {
      deps.agentAuthAdapter.getCurrentCredentials.mockResolvedValue({
        apiHost: "https://app.posthog.com",
        projectId: 1,
      });
      deps.agentAuthAdapter.buildMcpServers.mockResolvedValue({
        servers: [
          {
            name: "posthog",
            type: "http",
            url: "https://mcp.posthog.com/mcp",
            headers: [
              { name: "Authorization", value: "Bearer token" },
              { name: "x-posthog-mcp-consumer", value: "posthog-code" },
            ],
          },
        ],
        toolApprovals: {},
        toolInstallations: {},
      });

      await registeredResolver()("posthog");

      expect(deps.agentAuthAdapter.buildMcpServers).toHaveBeenCalledWith({
        apiHost: "https://app.posthog.com",
        projectId: 1,
      });
      expect(deps.mcpAppsService.addServerConfigs).toHaveBeenCalledWith([
        {
          name: "posthog",
          url: "https://mcp.posthog.com/mcp",
          headers: {
            Authorization: "Bearer token",
            "x-posthog-mcp-consumer": "posthog-code",
          },
        },
      ]);
    });

    it("no-ops when there are no current credentials", async () => {
      deps.agentAuthAdapter.getCurrentCredentials.mockResolvedValue(null);

      await registeredResolver()("posthog");

      expect(deps.agentAuthAdapter.buildMcpServers).not.toHaveBeenCalled();
      expect(deps.mcpAppsService.addServerConfigs).not.toHaveBeenCalled();
    });
  });

  describe("reconnect", () => {
    it("preserves conversation context when native reconnect fails", async () => {
      const apiClient = {};
      mockAgentConstructor.mockImplementationOnce(function (
        this: Record<string, unknown>,
      ) {
        this.run = mockAgentRun;
        this.cleanup = vi.fn().mockResolvedValue(undefined);
        this.getPosthogAPI = vi.fn(() => apiClient);
        this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
      });
      mockResumeFromLog.mockResolvedValue({ conversation: [{ role: "user" }] });
      mockFormatConversationForResume.mockReturnValue("User: previous request");
      mockResumeSession.mockRejectedValueOnce(new Error("not found"));
      await service.reconnectSession({
        ...baseSessionParams,
        adapter: "codex",
        sessionId: "old-session",
      });

      await service.prompt("run-1", [{ type: "text", text: "next request" }]);
      await service.prompt("run-1", [{ type: "text", text: "later request" }]);

      expect(mockPrompt.mock.calls[0][0].prompt).toEqual([
        expect.objectContaining({
          type: "text",
          text: expect.stringContaining("previous request"),
        }),
        { type: "text", text: "next request" },
      ]);
      expect(mockPrompt.mock.calls[1][0].prompt).toEqual([
        { type: "text", text: "later request" },
      ]);
    });

    it("preserves conversation context when reconnect has no session ID", async () => {
      mockAgentConstructor.mockImplementationOnce(function (
        this: Record<string, unknown>,
      ) {
        this.run = mockAgentRun;
        this.cleanup = vi.fn().mockResolvedValue(undefined);
        this.getPosthogAPI = vi.fn(() => ({}));
        this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
      });
      mockResumeFromLog.mockResolvedValue({ conversation: [{ role: "user" }] });
      mockFormatConversationForResume.mockReturnValue("User: previous request");

      await service.reconnectSession({
        ...baseSessionParams,
        adapter: "codex",
      });
      await service.prompt("run-1", [{ type: "text", text: "next request" }]);

      expect(mockPrompt.mock.calls[0][0].prompt[0].text).toContain(
        "previous request",
      );
    });

    it("reuses hydrated conversation when Claude resume fails", async () => {
      mockAgentConstructor.mockImplementationOnce(function (
        this: Record<string, unknown>,
      ) {
        this.run = mockAgentRun;
        this.cleanup = vi.fn().mockResolvedValue(undefined);
        this.getPosthogAPI = vi.fn(() => ({}));
        this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
      });
      mockHydrateSessionJsonl.mockResolvedValueOnce({
        hasSession: true,
        conversation: [{ role: "user", content: [] }],
      });
      mockFormatConversationForResume.mockReturnValue("User: hydrated request");
      mockResumeSession.mockRejectedValueOnce(new Error("not found"));

      await service.reconnectSession({
        ...baseSessionParams,
        adapter: "claude",
        sessionId: "old-session",
      });
      await service.prompt("run-1", [{ type: "text", text: "next request" }]);

      expect(mockResumeFromLog).not.toHaveBeenCalled();
      expect(mockPrompt.mock.calls[0][0].prompt[0].text).toContain(
        "hydrated request",
      );
    });

    it("does not resend hydrated conversation after native resume succeeds", async () => {
      mockAgentConstructor.mockImplementationOnce(function (
        this: Record<string, unknown>,
      ) {
        this.run = mockAgentRun;
        this.cleanup = vi.fn().mockResolvedValue(undefined);
        this.getPosthogAPI = vi.fn(() => ({}));
        this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
      });
      mockHydrateSessionJsonl.mockResolvedValueOnce({
        hasSession: true,
        conversation: [{ role: "user", content: [] }],
      });
      mockFormatConversationForResume.mockReturnValue("User: hydrated request");

      await service.reconnectSession({
        ...baseSessionParams,
        adapter: "claude",
        sessionId: "old-session",
      });
      await service.prompt("run-1", [{ type: "text", text: "next request" }]);

      expect(mockPrompt.mock.calls[0][0].prompt).toEqual([
        { type: "text", text: "next request" },
      ]);
    });

    it("retries recovered context after prompt failure", async () => {
      mockAgentConstructor.mockImplementationOnce(function (
        this: Record<string, unknown>,
      ) {
        this.run = mockAgentRun;
        this.cleanup = vi.fn().mockResolvedValue(undefined);
        this.getPosthogAPI = vi.fn(() => ({}));
        this.flushAllLogs = vi.fn().mockResolvedValue(undefined);
      });
      mockResumeFromLog.mockResolvedValue({ conversation: [{ role: "user" }] });
      mockFormatConversationForResume.mockReturnValue("User: previous request");
      mockPrompt.mockRejectedValueOnce(new Error("connection lost"));

      await service.reconnectSession({
        ...baseSessionParams,
        adapter: "codex",
      });
      await expect(
        service.prompt("run-1", [{ type: "text", text: "first attempt" }]),
      ).rejects.toThrow("connection lost");
      await service.prompt("run-1", [{ type: "text", text: "retry" }]);

      expect(mockPrompt.mock.calls[1][0].prompt[0].text).toContain(
        "previous request",
      );
    });
  });

  describe("MCP servers", () => {
    it("marks desktop sessions as local even though they have a taskRunId", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "codex",
      });

      expect(mockNewSession).toHaveBeenCalledTimes(1);
      expect(mockNewSession.mock.calls[0][0]._meta).toMatchObject({
        taskRunId: "run-1",
        environment: "local",
      });
    });

    it("passes MCP servers to newSession for codex adapter", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "codex",
      });

      expect(mockNewSession).toHaveBeenCalledTimes(1);
      const mcpServers = mockNewSession.mock.calls[0][0].mcpServers;
      expect(mcpServers).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            name: "posthog",
            type: "http",
            url: "https://mcp.posthog.com/mcp",
          }),
        ]),
      );
    });

    it("passes MCP servers to newSession for claude adapter", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "claude",
      });

      expect(mockNewSession).toHaveBeenCalledTimes(1);
      const mcpServers = mockNewSession.mock.calls[0][0].mcpServers;
      expect(mcpServers).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            name: "posthog",
            type: "http",
            url: "https://mcp.posthog.com/mcp",
          }),
        ]),
      );
    });

    it("passes the same MCP servers to codex as to claude without probing them first", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
      );

      await service.startSession({
        ...baseSessionParams,
        taskRunId: "run-claude",
        adapter: "claude",
      });
      await service.startSession({
        ...baseSessionParams,
        taskRunId: "run-codex",
        adapter: "codex",
      });

      const claudeMcp = mockNewSession.mock.calls[0][0].mcpServers;
      const codexMcp = mockNewSession.mock.calls[1][0].mcpServers;
      expect(claudeMcp).toHaveLength(1);
      expect(codexMcp).toEqual(claudeMcp);
    });

    it("passes reasoning effort to local Codex startup options", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "codex",
        effort: "xhigh",
      });

      expect(mockAgentRun).toHaveBeenCalledWith(
        "task-1",
        "run-1",
        expect.objectContaining({
          adapter: "codex",
          reasoningEffort: "xhigh",
        }),
      );
    });
  });

  describe("session meta", () => {
    it.each([{ spokenNarration: true }, { spokenNarration: false }])(
      "threads spokenNarration $spokenNarration into newSession meta",
      async ({ spokenNarration }) => {
        await service.startSession({
          ...baseSessionParams,
          adapter: "claude",
          spokenNarration,
        });

        expect(mockNewSession).toHaveBeenCalledTimes(1);
        expect(mockNewSession.mock.calls[0][0]._meta).toMatchObject({
          spokenNarration,
        });
      },
    );

    it("omits spokenNarration from newSession meta when unset", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "claude",
      });

      expect(mockNewSession).toHaveBeenCalledTimes(1);
      expect(mockNewSession.mock.calls[0][0]._meta).not.toHaveProperty(
        "spokenNarration",
      );
    });
  });

  describe("permission requests", () => {
    it("auto-approves after switching a live Codex session to full access", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "codex",
        permissionMode: "auto",
      });

      await service.setSessionConfigOption("run-1", "mode", "full-access");
      const responsePromise = mockAcpClient.current?.requestPermission({
        toolCall: {
          toolCallId: "tool-call-1",
          title: "Run command",
        },
        options: [
          { optionId: "reject", kind: "reject_once", name: "Reject" },
          { optionId: "allow", kind: "allow_once", name: "Allow" },
        ],
      });

      expect(service.getDebugSnapshot().pendingPermissions).toEqual([]);
      const response = await responsePromise;
      expect(response).toEqual({
        outcome: { outcome: "selected", optionId: "allow" },
      });
      expect(service.emit).not.toHaveBeenCalledWith(
        AgentServiceEvent.PermissionRequest,
        expect.anything(),
      );
      expect(deps.sleepService.release).not.toHaveBeenCalledWith("run-1");
    });

    it("still prompts for structured user questions in full access", async () => {
      await service.startSession({
        ...baseSessionParams,
        adapter: "codex",
        permissionMode: "full-access",
      });

      const responsePromise = mockAcpClient.current?.requestPermission({
        toolCall: {
          toolCallId: "question-1",
          title: "Which one?",
          _meta: { codeToolKind: "question" },
        },
        options: [
          { optionId: "option_0", kind: "allow_once", name: "A" },
          { optionId: "option_1", kind: "allow_once", name: "B" },
        ],
      });

      expect(service.getDebugSnapshot().pendingPermissions).toEqual([
        { taskRunId: "run-1", toolCallId: "question-1" },
      ]);
      expect(service.emit).toHaveBeenCalledWith(
        AgentServiceEvent.PermissionRequest,
        expect.objectContaining({ taskRunId: "run-1" }),
      );

      service.cancelPermission("run-1", "question-1");
      await expect(responsePromise).resolves.toEqual({
        outcome: { outcome: "cancelled" },
      });
    });
  });

  describe("session event subscriptions", () => {
    function serviceLog(svc: AgentService) {
      return (
        svc as unknown as {
          log: {
            info: ReturnType<typeof vi.fn>;
            warn: ReturnType<typeof vi.fn>;
          };
        }
      ).log;
    }

    function seedPendingSession(svc: AgentService, taskRunId: string) {
      (svc as unknown as { sessions: Map<string, unknown> }).sessions.set(
        taskRunId,
        { taskRunId, taskId: `task-for-${taskRunId}`, promptPending: true },
      );
    }

    function warnIfNoRendererListening(svc: AgentService, taskRunId: string) {
      (
        svc as unknown as { warnIfNoRendererListening(id: string): void }
      ).warnIfNoRendererListening(taskRunId);
    }

    it("delivers only the subscribed run's events and reports the close", async () => {
      const controller = new AbortController();
      const received: unknown[] = [];
      const consumed = (async () => {
        for await (const payload of service.subscribeSessionEvents(
          "run-1",
          controller.signal,
        )) {
          received.push(payload);
        }
      })();

      service.emit(AgentServiceEvent.SessionEvent, {
        taskRunId: "run-2",
        payload: "other",
      });
      service.emit(AgentServiceEvent.SessionEvent, {
        taskRunId: "run-1",
        payload: "mine",
      });
      controller.abort();
      await consumed;

      expect(received).toEqual(["mine"]);
      expect(serviceLog(service).info).toHaveBeenCalledWith(
        "Renderer session event subscription closed",
        expect.objectContaining({
          taskRunId: "run-1",
          delivered: 1,
          remainingSubscribers: 0,
        }),
      );
    });

    it("warns once a minute when a pending turn streams with nobody subscribed", () => {
      seedPendingSession(service, "run-1");

      warnIfNoRendererListening(service, "run-1");
      warnIfNoRendererListening(service, "run-1");

      expect(serviceLog(service).warn).toHaveBeenCalledTimes(1);
      expect(serviceLog(service).warn).toHaveBeenCalledWith(
        "Session events emitted while a prompt is pending but no renderer is subscribed",
        { taskRunId: "run-1", taskId: "task-for-run-1" },
      );
    });

    it("stays quiet while a renderer is subscribed", () => {
      seedPendingSession(service, "run-1");
      const controller = new AbortController();
      const consumed = (async () => {
        for await (const _ of service.subscribeSessionEvents(
          "run-1",
          controller.signal,
        )) {
          // drain
        }
      })();

      warnIfNoRendererListening(service, "run-1");
      controller.abort();

      expect(serviceLog(service).warn).not.toHaveBeenCalled();
      return consumed;
    });
  });

  describe("idle timeout", () => {
    function injectSession(
      svc: AgentService,
      taskRunId: string,
      overrides: Record<string, unknown> = {},
    ) {
      const sessions = (svc as unknown as { sessions: Map<string, unknown> })
        .sessions;
      sessions.set(taskRunId, {
        taskRunId,
        taskId: `task-for-${taskRunId}`,
        repoPath: "/mock/repo",
        agent: { cleanup: vi.fn().mockResolvedValue(undefined) },
        clientSideConnection: {},
        channel: `ch-${taskRunId}`,
        createdAt: Date.now(),
        lastActivityAt: Date.now(),
        config: {},
        promptPending: false,
        inFlightMcpToolCalls: new Map(),
        pendingSideQuestions: 0,
        mcpToolApprovals: {},
        toolInstallations: {},
        ...overrides,
      });
    }

    function getIdleTimeouts(svc: AgentService) {
      return (
        svc as unknown as {
          idleTimeouts: Map<
            string,
            { handle: ReturnType<typeof setTimeout>; deadline: number }
          >;
        }
      ).idleTimeouts;
    }

    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("recordActivity is a no-op for unknown sessions", () => {
      service.recordActivity("unknown-run");
      expect(getIdleTimeouts(service).size).toBe(0);
    });

    it("recordActivity sets a timeout for a known session", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");
      expect(getIdleTimeouts(service).has("run-1")).toBe(true);
    });

    it("recordActivity resets the timeout on subsequent calls", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");
      const firstDeadline = getIdleTimeouts(service).get("run-1")?.deadline;
      if (firstDeadline === undefined)
        throw new Error("Expected firstDeadline to be defined");

      vi.advanceTimersByTime(5 * 60 * 1000);
      service.recordActivity("run-1");
      const secondDeadline = getIdleTimeouts(service).get("run-1")
        ?.deadline as number;
      if (secondDeadline === undefined)
        throw new Error("Expected secondDeadline to be defined");

      expect(secondDeadline).toBeGreaterThan(firstDeadline);
    });

    it("kills idle session after timeout expires", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).toHaveBeenCalledWith(
        "session-idle-killed",
        expect.objectContaining({ taskRunId: "run-1" }),
      );
    });

    it("does not kill session if activity is recorded before timeout", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");

      vi.advanceTimersByTime(14 * 60 * 1000);
      service.recordActivity("run-1");
      vi.advanceTimersByTime(14 * 60 * 1000);

      expect(service.emit).not.toHaveBeenCalledWith(
        "session-idle-killed",
        expect.anything(),
      );
    });

    it("reschedules when promptPending is true at timeout", () => {
      injectSession(service, "run-1", { promptPending: true });
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).not.toHaveBeenCalledWith(
        "session-idle-killed",
        expect.anything(),
      );
      expect(getIdleTimeouts(service).has("run-1")).toBe(true);
    });

    it("reschedules when inFlightMcpToolCalls is non-empty at timeout", () => {
      const toolCalls = new Map([["tool-1", "some-mcp-tool"]]);
      injectSession(service, "run-1", { inFlightMcpToolCalls: toolCalls });
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).not.toHaveBeenCalledWith(
        "session-idle-killed",
        expect.anything(),
      );
      expect(getIdleTimeouts(service).has("run-1")).toBe(true);
    });

    it("kills session when inFlightMcpToolCalls is empty", () => {
      injectSession(service, "run-1", {
        inFlightMcpToolCalls: new Map(),
      });
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).toHaveBeenCalledWith(
        "session-idle-killed",
        expect.objectContaining({ taskRunId: "run-1" }),
      );
    });

    it("checkIdleDeadlines kills expired sessions on resume", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");

      const resumeHandler = (
        deps.powerManager.onResume.mock.calls[0] as unknown as [() => void]
      )[0];
      expect(resumeHandler).toBeDefined();

      vi.advanceTimersByTime(20 * 60 * 1000);
      resumeHandler();

      expect(service.emit).toHaveBeenCalledWith(
        "session-idle-killed",
        expect.objectContaining({ taskRunId: "run-1" }),
      );
    });

    it("reschedules when pendingSideQuestions is non-zero at timeout", () => {
      injectSession(service, "run-1", { pendingSideQuestions: 1 });
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).not.toHaveBeenCalledWith(
        "session-idle-killed",
        expect.anything(),
      );
      expect(getIdleTimeouts(service).has("run-1")).toBe(true);
    });

    it("kills session when pendingSideQuestions is zero", () => {
      injectSession(service, "run-1", { pendingSideQuestions: 0 });
      service.recordActivity("run-1");

      vi.advanceTimersByTime(15 * 60 * 1000);

      expect(service.emit).toHaveBeenCalledWith(
        "session-idle-killed",
        expect.objectContaining({ taskRunId: "run-1" }),
      );
    });

    it("checkIdleDeadlines does not kill non-expired sessions", () => {
      injectSession(service, "run-1");
      service.recordActivity("run-1");

      const resumeHandler = (
        deps.powerManager.onResume.mock.calls[0] as unknown as [() => void]
      )[0];

      vi.advanceTimersByTime(5 * 60 * 1000);
      resumeHandler();

      expect(service.emit).not.toHaveBeenCalledWith(
        "session-idle-killed",
        expect.anything(),
      );
    });
  });

  describe("sideQuestion", () => {
    function injectSession(
      svc: AgentService,
      taskRunId: string,
      overrides: Record<string, unknown> = {},
    ) {
      const sessions = (svc as unknown as { sessions: Map<string, unknown> })
        .sessions;
      sessions.set(taskRunId, {
        taskRunId,
        taskId: `task-for-${taskRunId}`,
        repoPath: "/mock/repo",
        agent: { cleanup: vi.fn().mockResolvedValue(undefined) },
        clientSideConnection: { extMethod: vi.fn() },
        channel: `ch-${taskRunId}`,
        createdAt: Date.now(),
        lastActivityAt: 0,
        config: { sessionId: "agent-session-1" },
        promptPending: false,
        inFlightMcpToolCalls: new Map(),
        pendingSideQuestions: 0,
        mcpToolApprovals: {},
        toolInstallations: {},
        ...overrides,
      });
    }

    it("throws when no session exists for the given id", async () => {
      await expect(service.sideQuestion("unknown-run", "why?")).rejects.toThrow(
        "Session not found: unknown-run",
      );
    });

    it("forwards the question to the adapter and returns the parsed answer", async () => {
      const extMethod = vi.fn().mockResolvedValue({ answer: "42" });
      injectSession(service, "run-1", {
        clientSideConnection: { extMethod },
      });

      const result = await service.sideQuestion("run-1", "why?");

      expect(result).toEqual({ answer: "42" });
      expect(extMethod).toHaveBeenCalledWith("_posthog/side_question", {
        sessionId: "agent-session-1",
        question: "why?",
      });
    });

    it("records activity on the session", async () => {
      const extMethod = vi.fn().mockResolvedValue({ answer: "42" });
      injectSession(service, "run-1", {
        clientSideConnection: { extMethod },
        lastActivityAt: 0,
      });
      const recordActivitySpy = vi.spyOn(service, "recordActivity");

      await service.sideQuestion("run-1", "why?");

      expect(recordActivitySpy).toHaveBeenCalledWith("run-1");
      const sessions = (
        service as unknown as {
          sessions: Map<string, { lastActivityAt: number }>;
        }
      ).sessions;
      expect(sessions.get("run-1")?.lastActivityAt).toBeGreaterThan(0);
    });

    it("throws when the adapter returns a malformed result", async () => {
      const extMethod = vi.fn().mockResolvedValue({ notAnAnswer: true });
      injectSession(service, "run-1", {
        clientSideConnection: { extMethod },
      });

      await expect(service.sideQuestion("run-1", "why?")).rejects.toThrow();
    });

    it("tracks pendingSideQuestions while the extension call is in flight", async () => {
      let resolveExtMethod: (value: { answer: string }) => void = () => {};
      const extMethod = vi.fn(
        () =>
          new Promise((resolve) => {
            resolveExtMethod = resolve;
          }),
      );
      injectSession(service, "run-1", { clientSideConnection: { extMethod } });
      const sessions = (
        service as unknown as {
          sessions: Map<string, { pendingSideQuestions: number }>;
        }
      ).sessions;

      const promise = service.sideQuestion("run-1", "why?");
      expect(sessions.get("run-1")?.pendingSideQuestions).toBe(1);

      resolveExtMethod({ answer: "42" });
      await promise;

      expect(sessions.get("run-1")?.pendingSideQuestions).toBe(0);
    });

    it("decrements pendingSideQuestions when the extension call fails", async () => {
      const extMethod = vi.fn().mockRejectedValue(new Error("boom"));
      injectSession(service, "run-1", { clientSideConnection: { extMethod } });
      const sessions = (
        service as unknown as {
          sessions: Map<string, { pendingSideQuestions: number }>;
        }
      ).sessions;

      await expect(service.sideQuestion("run-1", "why?")).rejects.toThrow(
        "boom",
      );

      expect(sessions.get("run-1")?.pendingSideQuestions).toBe(0);
    });
  });

  describe("channel system prompt repository isolation", () => {
    const credentials = { apiHost: "https://app.posthog.com", projectId: 1 };

    function buildChannelPrompt(systemPromptOverride?: string): string {
      return (
        service as unknown as {
          buildSystemPrompt: (
            credentials: { apiHost: string; projectId: number },
            taskId: string,
            cwd: string,
            customInstructions?: string,
            additionalDirectories?: string[],
            systemPromptOverride?: string,
            channelMode?: boolean,
          ) => { append: string };
        }
      ).buildSystemPrompt(
        credentials,
        "task-1",
        "/tmp/task-1",
        undefined,
        undefined,
        systemPromptOverride,
        true,
      ).append;
    }

    it.each([
      ["default", undefined],
      ["overridden", "Generate a canvas."],
    ])(
      "uses the shared session guidance for a %s session",
      (_name, systemPromptOverride) => {
        const prompt = buildChannelPrompt(systemPromptOverride);

        expect(prompt).toContain(PRODUCT_ENGINEER_PROMPT);
        expect(prompt).toContain(RICH_OUTPUT_TAGS_PROMPT);
        expect(prompt.indexOf(PRODUCT_ENGINEER_PROMPT)).toBeLessThan(
          prompt.indexOf(systemPromptOverride ?? "PostHog context:"),
        );
      },
    );

    it("requires a task-specific clone instead of an existing checkout", () => {
      const prompt = buildChannelPrompt();

      expect(prompt).toContain(
        "Do not `cd` into or edit an existing checkout elsewhere on the machine",
      );
      expect(prompt).toContain("use `clone_repo`");
      expect(prompt).toContain(
        "task-specific clone inside the scratch directory",
      );
      expect(prompt).not.toContain("Prefer reusing one of these");
    });
  });

  describe("system prompt questions", () => {
    it("requires blocking questions to use a structured user-input tool", () => {
      const prompt = (
        service as unknown as {
          buildSystemPrompt: (
            credentials: { apiHost: string; projectId: number },
            taskId: string,
            cwd: string,
          ) => { append: string };
        }
      ).buildSystemPrompt(
        { apiHost: "https://app.posthog.com", projectId: 1 },
        "task-1",
        "/tmp/task-1",
      ).append;

      expect(prompt).toContain(
        "use the structured user-input tool available in your current mode",
      );
      expect(prompt).toContain(
        "plain-text questions mark the task as finished",
      );
    });
  });
});

describe("buildAutoApproveOutcome", () => {
  it("prefers an allow_once option", () => {
    expect(
      buildAutoApproveOutcome([
        { optionId: "reject", kind: "reject_once", name: "Reject" },
        { optionId: "allow", kind: "allow_once", name: "Allow" },
      ]),
    ).toEqual({ outcome: "selected", optionId: "allow" });
  });

  it("prefers an allow_always option", () => {
    expect(
      buildAutoApproveOutcome([
        { optionId: "reject", kind: "reject_once", name: "Reject" },
        { optionId: "allow_always", kind: "allow_always", name: "Always" },
      ]),
    ).toEqual({ outcome: "selected", optionId: "allow_always" });
  });

  it("falls back to the first option when no allow option exists", () => {
    expect(
      buildAutoApproveOutcome([
        { optionId: "first", kind: "reject_once", name: "First" },
        { optionId: "second", kind: "reject_always", name: "Second" },
      ]),
    ).toEqual({ outcome: "selected", optionId: "first" });
  });

  it("returns a cancelled outcome when options is empty", () => {
    expect(buildAutoApproveOutcome([])).toEqual({ outcome: "cancelled" });
  });
});

describe("shouldAutoApprovePermissionRequest", () => {
  it.each([
    ["codex", "full-access", undefined, true],
    ["codex", "bypassPermissions", undefined, true],
    ["codex", "full-access", "question", false],
    ["codex", "auto", undefined, false],
    ["codex", "read-only", undefined, false],
    ["claude", "bypassPermissions", undefined, false],
    [undefined, "full-access", undefined, false],
  ])(
    "adapter %s in mode %s for %s => %s",
    (adapter, permissionMode, codeToolKind, expected) => {
      expect(
        shouldAutoApprovePermissionRequest(
          adapter,
          permissionMode,
          codeToolKind,
        ),
      ).toBe(expected);
    },
  );
});
