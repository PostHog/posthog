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
  formatGatewayModelName: vi.fn(),
  getProviderName: vi.fn(),
  isBlockedModelId: vi.fn().mockReturnValue(false),
}));

vi.mock("@posthog/agent/adapters/claude/session/jsonl-hydration", () => ({
  hydrateSessionJsonl: mockHydrateSessionJsonl,
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
import type { RegisteredFolder } from "../folders/schemas";
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
    foldersService: {
      getFolders: vi.fn().mockResolvedValue([]),
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

    // The Codex MCP reachability probe hits the network; default it to "reachable"
    // so unrelated session tests stay deterministic and offline-safe.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ body: null }));

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
      deps.foldersService as never,
      deps.loggerFactory as never,
    );
    vi.spyOn(service, "emit");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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

    it("passes identical MCP servers to both adapters when all servers are reachable", async () => {
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
      expect(codexMcp).toEqual(claudeMcp);
    });

    it("drops unreachable MCP servers for codex but keeps them for claude", async () => {
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

      // Claude connects to MCP lazily, so an unreachable server is harmless.
      expect(mockNewSession.mock.calls[0][0].mcpServers).toHaveLength(1);
      // codex-acp dies on an unreachable server, so it must be pruned.
      expect(mockNewSession.mock.calls[1][0].mcpServers).toHaveLength(0);
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

  describe("channel system prompt local folders", () => {
    const credentials = { apiHost: "https://app.posthog.com", projectId: 1 };
    const FOLDERS_HEADER =
      "already has these repositories checked out locally on this machine";

    function makeFolder(
      overrides: Partial<RegisteredFolder>,
    ): RegisteredFolder {
      return {
        id: "folder-id",
        path: "/src/example",
        name: "example",
        remoteUrl: null,
        lastAccessed: "2026-01-01T00:00:00.000Z",
        createdAt: "2026-01-01T00:00:00.000Z",
        ...overrides,
      };
    }

    function buildChannelPrompt(folders: RegisteredFolder[]): string {
      return (
        service as unknown as {
          buildSystemPrompt: (
            credentials: { apiHost: string; projectId: number },
            taskId: string,
            customInstructions?: string,
            additionalDirectories?: string[],
            systemPromptOverride?: string,
            channelMode?: boolean,
            knownLocalFolders?: RegisteredFolder[],
          ) => { append: string };
        }
      ).buildSystemPrompt(
        credentials,
        "task-1",
        undefined,
        undefined,
        undefined,
        true,
        folders,
      ).append;
    }

    it.each([
      {
        desc: "exists:true with a remoteUrl renders name, path and URL",
        folder: makeFolder({
          name: "posthog",
          path: "/src/posthog",
          remoteUrl: "git@github.com:PostHog/posthog.git",
          exists: true,
        }),
        included: true,
        line: "  - posthog — /src/posthog (git@github.com:PostHog/posthog.git)",
      },
      {
        desc: "exists undefined with a null remoteUrl renders without parens",
        folder: makeFolder({
          name: "local-only",
          path: "/src/local-only",
          remoteUrl: null,
        }),
        included: true,
        line: "  - local-only — /src/local-only",
      },
      {
        desc: "exists:false is filtered out and omits the block",
        folder: makeFolder({
          name: "stale",
          path: "/src/stale",
          exists: false,
        }),
        included: false,
        line: "  - stale — /src/stale",
      },
    ])("$desc", ({ folder, included, line }) => {
      const prompt = buildChannelPrompt([folder]);

      if (included) {
        expect(prompt).toContain(FOLDERS_HEADER);
        expect(prompt).toContain(line);
        // The reuse-first guidance only appears when a folder is on disk.
        expect(prompt).toContain("do NOT clone it again");
      } else {
        expect(prompt).not.toContain(line);
        // The only folder was filtered out, so the block is dropped entirely
        // and the prompt falls back to the "ask for a path" guidance.
        expect(prompt).not.toContain(FOLDERS_HEADER);
        expect(prompt).toContain("If the user names a folder or path");
      }
    });

    it("lists only existing folders when given a mix", () => {
      const prompt = buildChannelPrompt([
        makeFolder({
          id: "1",
          name: "posthog",
          path: "/src/posthog",
          remoteUrl: "git@github.com:PostHog/posthog.git",
          exists: true,
        }),
        makeFolder({ id: "2", name: "local-only", path: "/src/local-only" }),
        makeFolder({
          id: "3",
          name: "stale",
          path: "/src/stale",
          exists: false,
        }),
      ]);

      expect(prompt).toContain(FOLDERS_HEADER);
      expect(prompt).toContain(
        "  - posthog — /src/posthog (git@github.com:PostHog/posthog.git)",
      );
      expect(prompt).toContain("  - local-only — /src/local-only");
      // A null remoteUrl must not render an empty "()" suffix.
      expect(prompt).not.toContain("/src/local-only (");
      // exists:false folders never reach the prompt.
      expect(prompt).not.toContain("stale");
    });

    it("omits the local-folders block entirely when none are known", () => {
      const prompt = buildChannelPrompt([]);

      expect(prompt).not.toContain(FOLDERS_HEADER);
      expect(prompt).toContain("If the user names a folder or path");
    });
  });

  describe("system prompt questions", () => {
    it("requires blocking questions to use a structured user-input tool", () => {
      const prompt = (
        service as unknown as {
          buildSystemPrompt: (
            credentials: { apiHost: string; projectId: number },
            taskId: string,
          ) => { append: string };
        }
      ).buildSystemPrompt(
        { apiHost: "https://app.posthog.com", projectId: 1 },
        "task-1",
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
