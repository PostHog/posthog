import fs from "node:fs";
import { homedir, tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import {
  type Client,
  ClientSideConnection,
  type ContentBlock,
  ndJsonStream,
  PROTOCOL_VERSION,
  type RequestPermissionRequest,
  type RequestPermissionResponse,
  type SessionConfigOption,
  type SessionNotification,
} from "@agentclientprotocol/sdk";
import {
  detectRtkBinary,
  isMcpToolReadOnly,
  isNotification,
  POSTHOG_NOTIFICATIONS,
} from "@posthog/agent";
import type { McpToolApprovals } from "@posthog/agent/adapters/claude/mcp/tool-metadata";
import { hydrateSessionJsonl } from "@posthog/agent/adapters/claude/session/jsonl-hydration";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import { Agent } from "@posthog/agent/agent";
import {
  getAvailableCodexModes,
  getAvailableModes,
} from "@posthog/agent/execution-mode";
import {
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  fetchGatewayModels,
  formatGatewayModelName,
  type GatewayModel,
  getClaudeModelRecency,
  getProviderName,
  isAnthropicModel,
  isCloudflareModel,
  isOpenAIModel,
  pickAllowedModel,
} from "@posthog/agent/gateway-models";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import {
  findPrUrls,
  wasCreatedByLogin,
  wasCreatedRecently,
} from "@posthog/agent/pr-url-detector";
import {
  formatConversationForResume,
  resumeFromLog,
} from "@posthog/agent/resume";
import type * as AgentTypes from "@posthog/agent/types";
import { execGh } from "@posthog/git/gh";
import { getCurrentBranch } from "@posthog/git/queries";
import { APP_META_SERVICE, type IAppMeta } from "@posthog/platform/app-meta";
import {
  BUNDLED_RESOURCES_SERVICE,
  type IBundledResources,
} from "@posthog/platform/bundled-resources";
import {
  type IPowerManager,
  POWER_MANAGER_SERVICE,
} from "@posthog/platform/power-manager";
import {
  type IStoragePaths,
  STORAGE_PATHS_SERVICE,
} from "@posthog/platform/storage-paths";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import {
  type AcpMessage,
  type Adapter,
  type ExecutionMode,
  isAuthError,
  resolveCloudInitialPermissionMode,
  restrictedModelMeta,
  serializeError,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable, preDestroy } from "inversify";
import { WORKSPACE_REPOSITORY } from "../../db/identifiers";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { FoldersService } from "../folders/folders";
import { FOLDERS_SERVICE } from "../folders/identifiers";
import type { RegisteredFolder } from "../folders/schemas";
import { POSTHOG_PLUGIN_SERVICE } from "../posthog-plugin/identifiers";
import type { PosthogPluginService } from "../posthog-plugin/posthog-plugin";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import { loadSessionEnvOverrides } from "../session-env/loader";
import { isScratchPath } from "../workspace/scratch";
import type { AgentAuthAdapter, McpToolInstallations } from "./auth-adapter";
import { cleanupCodexHome, prepareCodexHome } from "./codex-home";
import { discoverExternalPlugins } from "./discover-plugins";
import {
  AGENT_AUTH_ADAPTER,
  AGENT_LOGGER,
  AGENT_MCP_APPS,
  AGENT_REPO_FILES,
  AGENT_SLEEP_COORDINATOR,
} from "./identifiers";
import type {
  AgentLogger,
  AgentMcpApps,
  AgentRepoFiles,
  AgentScopedLogger,
  AgentSleepCoordinator,
} from "./ports";
import {
  AgentServiceEvent,
  type AgentServiceEvents,
  type Credentials,
  type EffortLevel,
  type InterruptReason,
  type PromptOutput,
  type ReconnectSessionInput,
  type RtkStatus,
  type SessionResponse,
  type StartSessionInput,
} from "./schemas";

export type { InterruptReason };

function isDevBuild(): boolean {
  return process.env.POSTHOG_CODE_IS_DEV === "true";
}

/** Mark all content blocks as hidden so the renderer doesn't show a duplicate user message on retry */
type MessageCallback = (message: unknown) => void;

/** Shape of the `_meta.claudeCode` extension field on tool call updates. */
interface ClaudeCodeToolMeta {
  claudeCode?: { toolName?: string };
}

class NdJsonTap {
  private decoder = new TextDecoder();
  private buffer = "";

  constructor(private onMessage: MessageCallback) {}

  process(chunk: Uint8Array): void {
    this.buffer += this.decoder.decode(chunk, { stream: true });
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        this.onMessage(JSON.parse(line));
      } catch {
        // Not valid JSON, skip
      }
    }
  }
}

function createTappedReadableStream(
  underlying: ReadableStream<Uint8Array>,
  onMessage: MessageCallback,
  log: AgentScopedLogger,
): ReadableStream<Uint8Array> {
  const reader = underlying.getReader();
  const tap = new NdJsonTap(onMessage);

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { value, done } = await reader.read();
        if (done) {
          controller.close();
          return;
        }
        tap.process(value);
        controller.enqueue(value);
      } catch (err) {
        // Stream may be closed if subprocess crashed - close gracefully
        log.warn("Stream read failed (subprocess may have crashed)", {
          error: err,
        });
        controller.close();
      }
    },
    cancel() {
      // Release the reader when stream is cancelled
      reader.releaseLock();
    },
  });
}

function createTappedWritableStream(
  underlying: WritableStream<Uint8Array>,
  onMessage: MessageCallback,
  log: AgentScopedLogger,
): WritableStream<Uint8Array> {
  const tap = new NdJsonTap(onMessage);

  return new WritableStream<Uint8Array>({
    async write(chunk) {
      tap.process(chunk);
      try {
        const writer = underlying.getWriter();
        await writer.write(chunk);
        writer.releaseLock();
      } catch (err) {
        // Stream may be closed if subprocess crashed - log but don't throw
        log.warn("Stream write failed (subprocess may have crashed)", {
          error: err,
        });
      }
    },
    async close() {
      try {
        const writer = underlying.getWriter();
        await writer.close();
        writer.releaseLock();
      } catch {
        // Stream may already be closed
      }
    },
    async abort(reason) {
      try {
        const writer = underlying.getWriter();
        await writer.abort(reason);
        writer.releaseLock();
      } catch {
        // Stream may already be closed
      }
    },
  });
}

function makeOnAgentLog(loggerFactory: AgentLogger): AgentTypes.OnLogCallback {
  return (level, scope, message, data) => {
    const scopedLog = loggerFactory.scope(scope);
    if (data !== undefined) {
      scopedLog[level as keyof AgentScopedLogger](message, data);
    } else {
      scopedLog[level as keyof AgentScopedLogger](message);
    }
  };
}

function buildClaudeCodeOptions(args: {
  additionalDirectories?: string[];
  effort?: EffortLevel;
  plugins: { type: "local"; path: string }[];
  disallowedTools?: string[];
}) {
  return {
    ...(args.additionalDirectories?.length && {
      additionalDirectories: args.additionalDirectories,
    }),
    ...(args.effort && { effort: args.effort }),
    ...(args.disallowedTools?.length && {
      disallowedTools: args.disallowedTools,
    }),
    plugins: args.plugins,
  };
}

interface SessionConfig {
  taskId: string;
  taskRunId: string;
  repoPath: string;
  credentials: Credentials;
  logUrl?: string;
  /** The agent's session ID (for resume - SDK session ID for Claude, Codex's session ID for Codex) */
  sessionId?: string;
  adapter?: Adapter;
  /** Permission mode to use for the session */
  permissionMode?: string;
  /** Custom instructions injected into the system prompt */
  customInstructions?: string;
  /** Replaces the PostHog system prompt entirely (constrained surfaces). */
  systemPromptOverride?: string;
  /** Tool names denied for this session (passed to the Claude SDK). */
  disallowedTools?: string[];
  /** Effort level for Claude sessions */
  effort?: EffortLevel;
  /** Model to use for the session (e.g. "claude-sonnet-4-6") */
  model?: string;
  /** JSON Schema for structured task output — when set, the agent gets a create_output tool */
  jsonSchema?: Record<string, unknown> | null;
  /**
   * Session ID of an imported Claude Code CLI transcript already present in
   * CLAUDE_CONFIG_DIR. Starts the session via loadSession so prior history is
   * replayed to the client. Claude adapter only.
   */
  importedSessionId?: string;
  /** rtk command-output compression for this session; false opts out. */
  rtkEnabled?: boolean;
  /** The user's spoken-narration setting at session start. */
  spokenNarration?: boolean;
}

/** Pull the adapter's `agentCapabilities._meta.posthog.steering` from initialize. */
function extractSteeringCapability(init: unknown): string | undefined {
  const steering = (
    init as {
      agentCapabilities?: { _meta?: { posthog?: { steering?: unknown } } };
    }
  )?.agentCapabilities?._meta?.posthog?.steering;
  return typeof steering === "string" ? steering : undefined;
}

interface ManagedSession {
  taskRunId: string;
  taskId: string;
  repoPath: string;
  agent: Agent;
  clientSideConnection: ClientSideConnection;
  channel: string;
  createdAt: number;
  lastActivityAt: number;
  config: SessionConfig;
  interruptReason?: InterruptReason;
  promptPending: boolean;
  pendingContext?: string;
  configOptions?: SessionConfigOption[];
  /** Adapter's negotiated steering capability from initialize (`_meta.posthog.steering`). */
  steering?: string;
  /** Tracks in-flight MCP tool calls (toolCallId → toolKey) for cancellation */
  inFlightMcpToolCalls: Map<string, string>;
  /** MCP tool approval states fetched at session start */
  mcpToolApprovals: McpToolApprovals;
  /** Maps tool keys to their installation for backend approval updates */
  toolInstallations: McpToolInstallations;
  // Reset per session. `evaluatedPrUrls` dedupes the GitHub lookup per URL;
  // `prAttachChain` serializes attach writes so concurrent fetch-merge-patch
  // cycles can't drop each other's URLs from the accumulated list.
  evaluatedPrUrls: Set<string>;
  prAttachChain: Promise<void>;
}

/** Get the agent session ID from a managed session, throwing if not set. */
function getAgentSessionId(session: ManagedSession): string {
  const { sessionId } = session.config;
  if (!sessionId) {
    throw new Error(`Session ${session.taskRunId} has no agent session ID`);
  }
  return sessionId;
}

export function buildAutoApproveOutcome(
  options: RequestPermissionRequest["options"],
): RequestPermissionResponse["outcome"] {
  const allowOption = options.find(
    (o) => o.kind === "allow_once" || o.kind === "allow_always",
  );
  const optionId = allowOption?.optionId ?? options[0]?.optionId;
  if (!optionId) {
    return { outcome: "cancelled" };
  }
  return { outcome: "selected", optionId };
}

export function shouldAutoApprovePermissionRequest(
  adapter: string | undefined,
  permissionMode: string | undefined,
  codeToolKind?: string,
): boolean {
  if (adapter !== "codex" || !permissionMode || codeToolKind === "question") {
    return false;
  }
  return (
    resolveCloudInitialPermissionMode(
      "codex",
      permissionMode as ExecutionMode,
    ) === "full-access"
  );
}

interface PendingPermission {
  resolve: (response: RequestPermissionResponse) => void;
  reject: (error: Error) => void;
  taskRunId: string;
  toolCallId: string;
}

@injectable()
export class AgentService extends TypedEventEmitter<AgentServiceEvents> {
  // POSTHOG_CODE_AGENT_IDLE_TIMEOUT_MS overrides for dev/test only — the
  // memory bench shrinks it to verify idle reclaim in minutes.
  private static readonly IDLE_TIMEOUT_MS =
    Number(process.env.POSTHOG_CODE_AGENT_IDLE_TIMEOUT_MS) > 0
      ? Number(process.env.POSTHOG_CODE_AGENT_IDLE_TIMEOUT_MS)
      : 15 * 60 * 1000;

  private sessions = new Map<string, ManagedSession>();
  private pendingPermissions = new Map<string, PendingPermission>();
  private idleTimeouts = new Map<
    string,
    { handle: ReturnType<typeof setTimeout>; deadline: number }
  >();
  private processTracking: ProcessTrackingService;
  private sleepService: AgentSleepCoordinator;
  private fsService: AgentRepoFiles;
  private posthogPluginService: PosthogPluginService;
  private agentAuthAdapter: AgentAuthAdapter;
  private mcpAppsService: AgentMcpApps;
  private readonly log: AgentScopedLogger;
  private readonly onAgentLog: AgentTypes.OnLogCallback;

  constructor(
    @inject(PROCESS_TRACKING_SERVICE)
    processTracking: ProcessTrackingService,
    @inject(AGENT_SLEEP_COORDINATOR)
    sleepService: AgentSleepCoordinator,
    @inject(AGENT_REPO_FILES)
    fsService: AgentRepoFiles,
    @inject(POSTHOG_PLUGIN_SERVICE)
    posthogPluginService: PosthogPluginService,
    @inject(AGENT_AUTH_ADAPTER)
    agentAuthAdapter: AgentAuthAdapter,
    @inject(AGENT_MCP_APPS)
    mcpAppsService: AgentMcpApps,
    @inject(POWER_MANAGER_SERVICE)
    powerManager: IPowerManager,
    @inject(BUNDLED_RESOURCES_SERVICE)
    private readonly bundledResources: IBundledResources,
    @inject(APP_META_SERVICE)
    private readonly appMeta: IAppMeta,
    @inject(STORAGE_PATHS_SERVICE)
    private readonly storagePaths: IStoragePaths,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepository: IWorkspaceRepository,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly workspaceSettings: IWorkspaceSettings,
    @inject(FOLDERS_SERVICE)
    private readonly foldersService: FoldersService,
    @inject(AGENT_LOGGER)
    loggerFactory: AgentLogger,
  ) {
    super();
    this.processTracking = processTracking;
    this.sleepService = sleepService;
    this.fsService = fsService;
    this.posthogPluginService = posthogPluginService;
    this.agentAuthAdapter = agentAuthAdapter;
    this.mcpAppsService = mcpAppsService;
    this.log = loggerFactory.scope("agent-service");
    this.onAgentLog = makeOnAgentLog(loggerFactory);

    // Cloud runs never start a local session (the agent lives in the sandbox), so
    // getOrCreateSession never registers their MCP servers with the mcp-apps
    // service. Resolve them on demand from the current auth state the first time a
    // cloud-run UI-app resource is fetched, so the review card loads.
    this.mcpAppsService.setConfigResolver(async () => {
      const credentials = await this.agentAuthAdapter.getCurrentCredentials();
      if (credentials) {
        await this.ensureMcpAppsServerConfigs(credentials);
      }
    });

    powerManager.onResume(() => this.checkIdleDeadlines());
  }

  private getClaudeCliPath(): string {
    // Keep in sync with the destDir in apps/code/vite-main-plugins.mts
    // (copyClaudeExecutable plugin).
    const binary = process.platform === "win32" ? "claude.exe" : "claude";
    return this.bundledResources.resolve(`.vite/build/claude-cli/${binary}`);
  }

  /** Whether an rtk binary is installed on this host, independent of the toggle. */
  getRtkStatus(): RtkStatus {
    const binaryPath = detectRtkBinary(process.env);
    return {
      available: binaryPath !== undefined,
      binaryPath: binaryPath ?? null,
    };
  }

  private getCodexBinaryPath(): string {
    const binary = process.platform === "win32" ? "codex.exe" : "codex";
    return this.bundledResources.resolve(`.vite/build/codex-acp/${binary}`);
  }

  /**
   * Respond to a pending permission request from the UI.
   * This resolves the promise that the agent is waiting on.
   */
  public respondToPermission(
    taskRunId: string,
    toolCallId: string,
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
  ): void {
    const key = `${taskRunId}:${toolCallId}`;
    const pending = this.pendingPermissions.get(key);

    if (!pending) {
      this.log.warn("No pending permission found", { taskRunId, toolCallId });
      return;
    }

    this.log.info("Permission response received", {
      taskRunId,
      toolCallId,
      optionId,
      hasCustomInput: !!customInput,
      hasAnswers: !!answers,
    });

    const meta: Record<string, unknown> = {};
    if (customInput) meta.customInput = customInput;
    if (answers) meta.answers = answers;

    pending.resolve({
      outcome: {
        outcome: "selected",
        optionId,
      },
      ...(Object.keys(meta).length > 0 && { _meta: meta }),
    });

    this.pendingPermissions.delete(key);
    this.recordActivity(taskRunId);
  }

  /**
   * Cancel a pending permission request.
   * This resolves the promise with a "cancelled" outcome per ACP spec.
   */
  public cancelPermission(taskRunId: string, toolCallId: string): void {
    const key = `${taskRunId}:${toolCallId}`;
    const pending = this.pendingPermissions.get(key);

    if (!pending) {
      this.log.warn("No pending permission found to cancel", {
        taskRunId,
        toolCallId,
      });
      return;
    }

    this.log.info("Permission cancelled", { taskRunId, toolCallId });

    pending.resolve({
      outcome: {
        outcome: "cancelled",
      },
    });

    this.pendingPermissions.delete(key);
    this.recordActivity(taskRunId);
  }

  /**
   * Check if any sessions are currently active (i.e. have a prompt pending).
   */
  public hasActiveSessions(): boolean {
    for (const session of this.sessions.values()) {
      if (session.promptPending || session.inFlightMcpToolCalls.size > 0) {
        return true;
      }
    }
    return false;
  }

  public recordActivity(taskRunId: string): void {
    if (!this.sessions.has(taskRunId)) return;

    const existing = this.idleTimeouts.get(taskRunId);
    if (existing) clearTimeout(existing.handle);

    const deadline = Date.now() + AgentService.IDLE_TIMEOUT_MS;
    const handle = setTimeout(() => {
      this.killIdleSession(taskRunId);
    }, AgentService.IDLE_TIMEOUT_MS);

    this.idleTimeouts.set(taskRunId, { handle, deadline });
  }

  private killIdleSession(taskRunId: string): void {
    const session = this.sessions.get(taskRunId);
    if (!session) return;
    if (session.promptPending || session.inFlightMcpToolCalls.size > 0) {
      this.recordActivity(taskRunId);
      return;
    }
    this.log.info("Killing idle session", {
      taskRunId,
      taskId: session.taskId,
    });
    this.emit(AgentServiceEvent.SessionIdleKilled, {
      taskRunId,
      taskId: session.taskId,
    });
    this.cleanupSession(taskRunId).catch((err) => {
      this.log.error("Failed to cleanup idle session", { taskRunId, err });
    });
  }

  private checkIdleDeadlines(): void {
    const now = Date.now();
    const expired = [...this.idleTimeouts.entries()].filter(
      ([, { deadline }]) => now >= deadline,
    );
    for (const [taskRunId, { handle }] of expired) {
      clearTimeout(handle);
      this.killIdleSession(taskRunId);
    }
  }

  private buildSystemPrompt(
    credentials: Credentials,
    taskId: string,
    customInstructions?: string,
    additionalDirectories?: string[],
    systemPromptOverride?: string,
    channelMode?: boolean,
    knownLocalFolders?: RegisteredFolder[],
  ): {
    append: string;
  } {
    // A constrained surface (e.g. the canvas generator) supplies its own prompt
    // and does NOT want the default coding/attribution guidance.
    if (systemPromptOverride) {
      return { append: systemPromptOverride };
    }

    let prompt = `PostHog context: use project ${credentials.projectId} on ${credentials.apiHost}. When using PostHog MCP tools, operate only on this project.`;

    prompt += `

## Attribution
Do NOT use Claude Code's default attribution (no "Co-Authored-By" trailers, no "Generated with [Claude Code]" lines).

Instead, add the following trailers to EVERY commit message (after a blank line at the end):
  Generated-By: PostHog Code
  Task-Id: ${taskId}

Example:
\`\`\`
git commit -m "$(cat <<'EOF'
fix: resolve login redirect loop

Generated-By: PostHog Code
Task-Id: ${taskId}
EOF
)"
\`\`\`

When creating new branches, prefix them with \`posthog-code/\` (e.g. \`posthog-code/fix-login-redirect\`).

When creating pull requests, add the following footer at the end of the PR description:
\`\`\`
---
*Created with [PostHog Code](https://posthog.com/code?ref=pr)*
\`\`\`

When you mention a pull request in any reply or summary, always hyperlink it to its full URL (e.g. a Markdown link like [#123](https://github.com/org/repo/pull/123)) rather than plain text, so readers can open it directly.

## Questions
When you need an answer from the user before you can continue, use the structured user-input tool available in your current mode. Never end a turn with a blocking question in a normal assistant message because plain-text questions mark the task as finished instead of waiting for the user's response.

## Shell efficiency
Optimize for the fewest shell round trips.
- Batch related commands into one Bash invocation using \`&&\` (e.g. \`npm run typecheck && npm run lint && npm test\`).
- Emit all independent tool calls in the same response.
- Read multiple files at once.
- Never rerun a command solely to reproduce output you already have.`;

    if (channelMode) {
      const localFolders = (knownLocalFolders ?? []).filter(
        (f) => f.exists !== false,
      );
      const localFoldersBlock = localFolders.length
        ? `\n\nThe user already has these repositories checked out locally on this machine. Prefer reusing one of these over cloning anything:\n${localFolders
            .map(
              (f) =>
                `  - ${f.name} — ${f.path}${f.remoteUrl ? ` (${f.remoteUrl})` : ""}`,
            )
            .join("\n")}`
        : "";

      prompt += `

## Channel task (no repository attached)
You are running in a PostHog channel as a general-purpose assistant. This task may NOT need a code repository at all — it could be data analysis via PostHog tools, drafting a message, or answering a question. Do not assume you need a repo.

- Your working directory is a scratch directory, not a git checkout. Treat it as empty.
- Decide from the user's request (and the channel CONTEXT.md included above, if any) whether the task actually requires working inside a code repository. If it doesn't, just do the work in the scratch directory — do NOT attach a repo.

If a repository IS genuinely required, attach one in this priority order:
1. **Reuse a folder the user already has locally.** ${localFolders.length ? "Pick the one that best matches the request and the channel CONTEXT.md, then `cd` into its absolute path and do all git and file work there. It is already on disk — do NOT clone it again." : "If the user names a folder or path, `cd` into that absolute path and work there."}
2. **If you can't confidently pick one** (none clearly match, or it's ambiguous), use the AskUserQuestion tool to ask the user which local folder to use, or for the path where the folder lives on this machine. Do not guess.
3. **Only as a last resort** — when the user has no local copy, or explicitly wants a fresh checkout — clone from remote. Call \`list_repos\` to see what's available (prefer repos named in CONTEXT.md), then **confirm with the user via AskUserQuestion before cloning**, and use \`clone_repo\` (pass \`owner/repo\`); it clones into a subdirectory of your working directory and returns the path to \`cd\` into.${localFoldersBlock}`;
    }

    if (customInstructions) {
      prompt += `\n\nUser custom instructions:\n${customInstructions}`;
    }

    if (additionalDirectories?.length) {
      const escapeXml = (s: string) =>
        s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const dirs = additionalDirectories
        .map((d) => `  <directory>${escapeXml(d)}</directory>`)
        .join("\n");
      prompt += `\n\nThe user has granted you access to additional directories outside the working directory. You may read and edit files in these paths just like the working directory:\n<additional_directories>\n${dirs}\n</additional_directories>`;
    }

    return { append: prompt };
  }

  async startSession(params: StartSessionInput): Promise<SessionResponse> {
    this.validateSessionParams(params);
    const config = this.toSessionConfig(params);
    const session = await this.getOrCreateSession(config, false);
    return this.toSessionResponse(session);
  }

  /**
   * Register the MCP server configs (posthog + installations) with the mcp-apps
   * service without starting an agent session. A cloud run's agent lives in the
   * sandbox, so getOrCreateSession never runs on the desktop and the mcp-apps
   * service has no config to fetch a UI-app resource through — the review card
   * then fails with "No server config for: posthog" and renders as text.
   * Invoked via the config resolver registered in the constructor.
   */
  private async ensureMcpAppsServerConfigs(
    credentials: Credentials,
  ): Promise<void> {
    const { servers } =
      await this.agentAuthAdapter.buildMcpServers(credentials);
    this.mcpAppsService.addServerConfigs(
      servers.map((s) => ({
        name: s.name,
        url: s.url,
        headers: Object.fromEntries(s.headers.map((h) => [h.name, h.value])),
      })),
    );
  }

  async reconnectSession(
    params: ReconnectSessionInput,
  ): Promise<SessionResponse | null> {
    try {
      this.validateSessionParams(params);
    } catch (err) {
      this.log.error("Invalid reconnect params", err);
      return null;
    }

    const config = this.toSessionConfig(params);
    const session = await this.getOrCreateSession(config, true);
    return session ? this.toSessionResponse(session) : null;
  }

  private async getOrCreateSession(
    config: SessionConfig,
    isReconnect: false,
    isRetry?: boolean,
  ): Promise<ManagedSession>;
  private async getOrCreateSession(
    config: SessionConfig,
    isReconnect: true,
    isRetry?: boolean,
  ): Promise<ManagedSession | null>;
  private async getOrCreateSession(
    config: SessionConfig,
    isReconnect: boolean,
    isRetry = false,
  ): Promise<ManagedSession | null> {
    const {
      taskId,
      taskRunId,
      repoPath: rawRepoPath,
      credentials,
      logUrl,
      adapter,
      permissionMode,
      customInstructions,
      systemPromptOverride,
      disallowedTools,
      effort,
      model,
      jsonSchema,
    } = config;

    // Preview config doesn't need a real repo — use a temp directory
    const repoPath = taskId === "__preview__" ? tmpdir() : rawRepoPath;

    // Repo-less channel tasks run in a scratch dir. Detecting it server-side
    // (rather than plumbing a flag from the client) keeps channel mode correct
    // across reconnects, where the same scratch repoPath is passed back in.
    const channelMode = isScratchPath(
      repoPath,
      this.workspaceSettings.getWorktreeLocation(),
    );

    // In channel mode the agent decides at runtime whether it needs a repo. Give
    // it the user's previously-used local folders so it can reuse one (or ask)
    // instead of cloning from remote. Only fetched for channel sessions.
    const knownLocalFolders = channelMode
      ? await this.foldersService.getFolders().catch(() => [])
      : [];

    const additionalDirectories =
      taskId === "__preview__"
        ? []
        : this.workspaceRepository.getAdditionalDirectories(taskId);

    if (!isRetry) {
      const existing = this.sessions.get(taskRunId);
      if (existing) {
        return existing;
      }

      for (const proc of this.processTracking.getByTaskId(taskId)) {
        if (
          (proc.category === "agent" || proc.category === "child") &&
          proc.metadata?.taskRunId === taskRunId
        ) {
          this.processTracking.kill(proc.pid);
        }
      }

      // Clean up any prior session for this taskRunId before creating a new one
      await this.cleanupSession(taskRunId);
    }

    const channel = `agent-event:${taskRunId}`;
    const proxyUrl = await this.agentAuthAdapter.ensureGatewayProxy(
      credentials.apiHost,
    );
    await this.agentAuthAdapter.configureProcessEnv({
      credentials,
      proxyUrl,
      claudeCliPath: this.getClaudeCliPath(),
      rtkEnabled: config.rtkEnabled,
    });

    const isPreview = taskId === "__preview__";

    const agent = new Agent({
      posthog: {
        ...this.agentAuthAdapter.createPosthogConfig(credentials),
        userAgent: `posthog/desktop.hog.dev; version: ${this.appMeta.version}`,
      },
      skipLogPersistence: isPreview,
      localCachePath: join(homedir(), ".posthog-code"),
      debug: isDevBuild(),
      onLog: this.onAgentLog,
    });
    let fallbackResumeContext: string | undefined;
    let hydratedResumeContext: string | undefined;

    try {
      const systemPrompt = this.buildSystemPrompt(
        credentials,
        taskId,
        customInstructions,
        additionalDirectories,
        systemPromptOverride,
        channelMode,
        knownLocalFolders,
      );

      const bundledSkillsDir = join(
        this.posthogPluginService.getPluginPath(),
        "skills",
      );

      let codexHome: string | undefined;
      if (adapter === "codex") {
        try {
          codexHome = await prepareCodexHome({
            appDataPath: this.storagePaths.appDataPath,
            taskRunId,
            bundledSkillsDir,
            log: this.log,
          });
        } catch (err) {
          // A skills-prep failure must not kill the session; Codex falls back
          // to its default home and the user's own ~/.agents/skills.
          this.log.warn("Failed to prepare codex home", {
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }

      const acpConnection = await agent.run(taskId, taskRunId, {
        adapter,
        gatewayUrl: proxyUrl,
        codexBinaryPath:
          adapter === "codex" ? this.getCodexBinaryPath() : undefined,
        codexHome,
        model,
        reasoningEffort: adapter === "codex" ? effort : undefined,
        developerInstructions:
          adapter === "codex" ? systemPrompt.append : undefined,
        additionalDirectories:
          adapter === "codex" ? additionalDirectories : undefined,
        onStructuredOutput: jsonSchema
          ? async (output) => {
              const posthogAPI = agent.getPosthogAPI();
              if (posthogAPI) {
                await posthogAPI.updateTaskRun(taskId, taskRunId, { output });
              }
            }
          : undefined,
        processCallbacks: {
          onProcessSpawned: (info) => {
            this.processTracking.register(
              info.pid,
              "agent",
              `agent:${taskRunId}`,
              {
                taskRunId,
                taskId,
                command: info.command,
              },
              taskId,
            );
          },
          onProcessExited: (pid) => {
            this.processTracking.unregister(pid, "agent-exited");
          },
          onMcpServersReady: (serverNames) => {
            this.mcpAppsService.handleDiscovery(serverNames).catch((err) => {
              this.log.warn("MCP Apps discovery failed", {
                error: err instanceof Error ? err.message : String(err),
              });
            });
          },
        },
      });
      const { clientStreams } = acpConnection;

      const connection = this.createClientConnection(
        taskRunId,
        channel,
        clientStreams,
      );

      const initResult = await connection.initialize({
        protocolVersion: PROTOCOL_VERSION,
        clientCapabilities: {
          fs: {
            readTextFile: true,
            writeTextFile: true,
          },
          terminal: true,
        },
      });
      // The adapter advertises whether mid-turn steering folds natively into the
      // running turn (`steering: "native"`) vs needs cancel+resend. Surface it so
      // the host gates steer-vs-resend on the negotiated capability, not on a
      // hardcoded adapter name (codex-acp advertises "interrupt-resend").
      const steering = extractSteeringCapability(initResult);

      const {
        servers: mcpServers,
        toolApprovals,
        toolInstallations,
      } = await this.agentAuthAdapter.buildMcpServers(credentials);

      // Store server configs for lazy MCP connections — actual connections
      // are created on-demand when UI resources are first requested.
      this.mcpAppsService.setServerConfigs(
        mcpServers.map((s) => ({
          name: s.name,
          url: s.url,
          headers: Object.fromEntries(s.headers.map((h) => [h.name, h.value])),
        })),
      );

      // codex-acp connects to every MCP server eagerly during session creation
      // and treats an unreachable one as fatal, which kills the session
      // ("ACP connection closed") and makes the host silently fall back to a
      // Claude/Opus session. Claude connects lazily and is unaffected, so only
      // the Codex server list is pruned to the reachable ones.
      const sessionMcpServers =
        adapter === "codex"
          ? await this.filterReachableMcpServers(mcpServers, taskRunId)
          : mcpServers;

      let externalPlugins: Awaited<ReturnType<typeof discoverExternalPlugins>> =
        [];
      try {
        externalPlugins = await discoverExternalPlugins(
          {
            userDataDir: this.storagePaths.appDataPath,
            repoPath,
            bundledSkillsDir,
          },
          this.log,
        );
      } catch (err) {
        this.log.warn("Failed to discover external plugins", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
      const plugins = [
        {
          type: "local" as const,
          path: this.posthogPluginService.getPluginPath(),
        },
        ...externalPlugins,
      ];
      const claudeCodeOptions = buildClaudeCodeOptions({
        additionalDirectories,
        effort,
        plugins,
        disallowedTools,
      });

      let configOptions: SessionConfigOption[] | undefined;
      let agentSessionId: string | undefined;

      if (isReconnect && !config.sessionId) {
        fallbackResumeContext = await this.loadFallbackResumeContext(
          agent,
          config,
        );
      }

      // Imported Claude Code CLI session: the transcript JSONL was copied
      // into CLAUDE_CONFIG_DIR at import time, so load it directly and let
      // the adapter replay its history to the client. On failure, fall
      // through to a fresh session so the task still starts.
      if (!isReconnect && config.importedSessionId && adapter !== "codex") {
        const importedSessionId = config.importedSessionId;
        try {
          const loadResponse = await connection.loadSession({
            sessionId: importedSessionId,
            cwd: repoPath,
            mcpServers: sessionMcpServers,
            _meta: {
              ...(logUrl && {
                persistence: { taskId, runId: taskRunId, logUrl },
              }),
              taskRunId,
              environment: "local",
              sessionId: importedSessionId,
              systemPrompt,
              ...(channelMode && { channelMode }),
              ...(config.spokenNarration !== undefined && {
                spokenNarration: config.spokenNarration,
              }),
              mcpToolApprovals: toolApprovals,
              ...(permissionMode && { permissionMode }),
              ...(model != null && { model }),
              ...(jsonSchema && { jsonSchema }),
              claudeCode: {
                options: claudeCodeOptions,
              },
            },
          });
          configOptions = loadResponse?.configOptions ?? undefined;
          agentSessionId = importedSessionId;
        } catch (err) {
          this.log.warn(
            "Failed to load imported session, creating new session instead",
            {
              taskId,
              taskRunId,
              error: err instanceof Error ? err.message : String(err),
            },
          );
        }
      }

      // Claude-specific: hydrate session JSONL from PostHog before resuming.
      // If hydration finds no conversation to restore, skip the resume and
      // fall through to creating a new session. This avoids a doomed
      // resumeSession that would fail with "Resource not found"
      if (isReconnect && config.sessionId) {
        const existingSessionId = config.sessionId;

        if (adapter !== "codex") {
          const posthogAPI = agent.getPosthogAPI();
          if (posthogAPI) {
            const hydration = await hydrateSessionJsonl({
              sessionId: existingSessionId,
              cwd: repoPath,
              taskId,
              runId: taskRunId,
              permissionMode: config.permissionMode,
              posthogAPI,
              log: this.log,
            });
            if (hydration.conversation) {
              hydratedResumeContext = this.formatFallbackResumeContext(
                hydration.conversation,
              );
            }
            if (!hydration.hasSession) {
              this.log.info(
                "No session JSONL to resume, creating new session instead",
                { taskId, taskRunId },
              );
              fallbackResumeContext ??=
                hydratedResumeContext ??
                (await this.loadFallbackResumeContext(agent, config));
              config.sessionId = undefined;
            }
          }
        }
      }

      if (isReconnect && config.sessionId) {
        const existingSessionId = config.sessionId;

        // Both adapters implement resumeSession:
        // - Claude: delegates to SDK's resumeSession with JSONL hydration
        // - Codex: delegates to codex-acp's loadSession internally
        const resumeResponse = await connection.resumeSession({
          sessionId: existingSessionId,
          cwd: repoPath,
          mcpServers: sessionMcpServers,
          _meta: {
            ...(logUrl && {
              persistence: { taskId, runId: taskRunId, logUrl },
            }),
            taskRunId,
            environment: "local",
            sessionId: existingSessionId,
            systemPrompt,
            ...(channelMode && { channelMode }),
            ...(config.spokenNarration !== undefined && {
              spokenNarration: config.spokenNarration,
            }),
            mcpToolApprovals: toolApprovals,
            ...(permissionMode && { permissionMode }),
            ...(model != null && { model }),
            ...(jsonSchema && { jsonSchema }),
            claudeCode: {
              options: claudeCodeOptions,
            },
          },
        });
        configOptions = resumeResponse?.configOptions ?? undefined;
        agentSessionId = existingSessionId;
      } else if (agentSessionId === undefined) {
        if (isReconnect) {
          this.log.info("No sessionId for reconnect, creating new session", {
            taskId,
            taskRunId,
          });
        }
        const newSessionResponse = await connection.newSession({
          cwd: repoPath,
          mcpServers: sessionMcpServers,
          _meta: {
            taskRunId,
            environment: "local",
            systemPrompt,
            ...(channelMode && { channelMode }),
            ...(config.spokenNarration !== undefined && {
              spokenNarration: config.spokenNarration,
            }),
            mcpToolApprovals: toolApprovals,
            ...(permissionMode && { permissionMode }),
            ...(model != null && { model }),
            ...(jsonSchema && { jsonSchema }),
            claudeCode: {
              options: claudeCodeOptions,
            },
          },
        });
        configOptions = newSessionResponse.configOptions ?? undefined;
        agentSessionId = newSessionResponse.sessionId;
      }

      config.sessionId = agentSessionId;

      const session: ManagedSession = {
        taskRunId,
        taskId,
        repoPath,
        agent,
        clientSideConnection: connection,
        channel,
        createdAt: Date.now(),
        lastActivityAt: Date.now(),
        config,
        promptPending: false,
        configOptions,
        steering,
        inFlightMcpToolCalls: new Map(),
        mcpToolApprovals: toolApprovals,
        toolInstallations,
        evaluatedPrUrls: new Set(),
        prAttachChain: Promise.resolve(),
        pendingContext: fallbackResumeContext,
      };

      this.sessions.set(taskRunId, session);
      this.recordActivity(taskRunId);

      if (isRetry) {
        this.log.info("Session created after auth retry", { taskRunId });
      }
      return session;
    } catch (err) {
      if (
        fallbackResumeContext === undefined &&
        isReconnect &&
        !isRetry &&
        !isAuthError(err)
      ) {
        fallbackResumeContext =
          hydratedResumeContext ??
          (await this.loadFallbackResumeContext(agent, config));
      }
      try {
        await agent.cleanup();
      } catch {
        this.log.debug("Agent cleanup failed during error handling", {
          taskRunId,
        });
      }

      if (!isRetry && isAuthError(err)) {
        this.log.warn(
          `Auth error during ${isReconnect ? "reconnect" : "create"}, retrying`,
          { taskRunId },
        );
        if (isReconnect) {
          return this.getOrCreateSession(config, true, true);
        }
        return this.getOrCreateSession(config, false, true);
      }
      // When the in-process ACP layer masks a thrown error as a generic
      // "Internal error", the real text survives in `data.details`. Surface it
      // here (host-side, before the tRPC boundary drops `data`) so the exported
      // log names the actual cause.
      const maskedDetail = (err as { data?: { details?: unknown } })?.data
        ?.details;
      const detailSuffix =
        typeof maskedDetail === "string" && maskedDetail
          ? `: ${maskedDetail}`
          : "";
      const action = isReconnect ? "reconnect" : "create";
      this.log.error(
        `Failed to ${action} session${isRetry ? " after retry" : ""}${detailSuffix}`,
        {
          taskRunId,
          taskId,
          sessionId: config.sessionId,
          adapter: config.adapter,
          model: config.model,
          isRetry,
          data: (err as { data?: unknown }).data,
          errorDetail: serializeError(err),
        },
      );
      // Non-auth reconnect failure on first attempt: fall back to a fresh session.
      // If this was already an auth retry (isRetry=true), we've exhausted retries
      // and return null to avoid infinite loops.
      if (isReconnect && !isRetry) {
        this.log.warn("Reconnect failed, falling back to new session", {
          taskRunId,
          taskId,
          sessionId: config.sessionId,
        });
        config.sessionId = undefined;
        const session = await this.getOrCreateSession(config, false, false);
        session.pendingContext = fallbackResumeContext;
        return session;
      }
      if (isReconnect) return null;
      throw err;
    }
  }

  private async loadFallbackResumeContext(
    agent: Agent,
    config: SessionConfig,
  ): Promise<string | undefined> {
    const apiClient = agent.getPosthogAPI();
    if (!apiClient) return undefined;

    try {
      const state = await resumeFromLog({
        taskId: config.taskId,
        runId: config.taskRunId,
        repositoryPath: config.repoPath,
        apiClient,
      });
      return this.formatFallbackResumeContext(state.conversation);
    } catch (err) {
      this.log.warn("Failed to restore conversation for fallback session", {
        taskId: config.taskId,
        taskRunId: config.taskRunId,
        error: err instanceof Error ? err.message : String(err),
      });
      return undefined;
    }
  }

  private formatFallbackResumeContext(
    conversation: Parameters<typeof formatConversationForResume>[0],
  ): string | undefined {
    const history = formatConversationForResume(conversation);
    if (!history) return undefined;
    return `You are resuming a previous conversation after the native session could not be restored. Here is the conversation history from the previous session:\n\n${history}\n\nContinue from where you left off when responding to the user's next message.`;
  }

  private async filterReachableMcpServers<
    T extends {
      name: string;
      url: string;
      headers: Array<{ name: string; value: string }>;
    },
  >(servers: T[], taskRunId: string): Promise<T[]> {
    const probed = await Promise.all(
      servers.map(async (server) => ({
        server,
        reachable: await this.isMcpServerReachable(server),
      })),
    );
    const reachable: T[] = [];
    for (const { server, reachable: ok } of probed) {
      if (ok) {
        reachable.push(server);
      } else {
        this.log.warn(
          "Dropping unreachable MCP server from Codex session; codex-acp treats an unreachable server as a fatal startup error",
          { taskRunId, server: server.name, url: server.url },
        );
      }
    }
    return reachable;
  }

  private async isMcpServerReachable(server: {
    url: string;
    headers: Array<{ name: string; value: string }>;
  }): Promise<boolean> {
    const PROBE_TIMEOUT_MS = 2_000;
    try {
      const headers: Record<string, string> = {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
      };
      for (const header of server.headers) {
        headers[header.name] = header.value;
      }
      const response = await fetch(server.url, {
        method: "POST",
        headers,
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 0,
          method: "initialize",
          params: {
            protocolVersion: "2025-06-18",
            capabilities: {},
            clientInfo: { name: "posthog-code", version: "1.0.0" },
          },
        }),
        signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
      });
      // Release the body without draining it. A cancel rejection (e.g. an
      // already-disturbed stream) is a cleanup detail, not a reachability
      // signal, so it must not flip the result to unreachable.
      try {
        await response.body?.cancel();
      } catch {
        // ignore body cleanup failures
      }
      // Any HTTP response means the endpoint is reachable. codex-acp only treats
      // transport failures (connection refused, DNS, timeout) as fatal; HTTP or
      // JSON-RPC error responses are handled gracefully.
      return true;
    } catch (err) {
      this.log.debug("MCP server reachability probe failed", {
        url: server.url,
        error: err instanceof Error ? err.message : String(err),
      });
      return false;
    }
  }

  async prompt(
    sessionId: string,
    prompt: ContentBlock[],
    options?: { steer?: boolean },
  ): Promise<PromptOutput> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    // A steer is injected into the turn that is already running, which owns the
    // promptPending/sleep/idle lifecycle. Forward it fire-and-forget so this
    // call does not flip that shared state out from under the live turn.
    if (options?.steer) {
      const result = await session.clientSideConnection.prompt({
        sessionId: getAgentSessionId(session),
        prompt,
        _meta: { steer: true },
      });
      return {
        stopReason: result.stopReason,
        _meta: result._meta as PromptOutput["_meta"],
      };
    }

    // Prepend pending context if present
    let finalPrompt = prompt;
    const pendingContext = session.pendingContext;
    if (pendingContext) {
      this.log.info("Prepending context to prompt", { sessionId });
      finalPrompt = [
        {
          type: "text",
          text: `_${pendingContext}_\n\n`,
          _meta: { ui: { hidden: true } },
        },
        ...prompt,
      ];
      session.pendingContext = undefined;
    }

    session.lastActivityAt = Date.now();
    session.promptPending = true;
    this.recordActivity(sessionId);
    this.sleepService.acquire(sessionId);

    try {
      try {
        const result = await session.clientSideConnection.prompt({
          sessionId: getAgentSessionId(session),
          prompt: finalPrompt,
        });
        return {
          stopReason: result.stopReason,
          _meta: result._meta as PromptOutput["_meta"],
        };
      } catch (err) {
        if (pendingContext && session.pendingContext === undefined) {
          session.pendingContext = pendingContext;
        }
        throw err;
      }
    } finally {
      session.promptPending = false;
      session.lastActivityAt = Date.now();
      this.recordActivity(sessionId);
      this.sleepService.release(sessionId);

      if (!this.hasActiveSessions()) {
        this.emit(AgentServiceEvent.SessionsIdle, undefined);
      }
    }
  }

  async cancelSession(sessionId: string): Promise<boolean> {
    const session = this.sessions.get(sessionId);
    if (!session) return false;

    try {
      await this.cleanupSession(sessionId);
      return true;
    } catch (_err) {
      return false;
    }
  }

  async cancelSessionsByTaskId(taskId: string): Promise<void> {
    for (const [taskRunId, session] of this.sessions) {
      if (session.taskId === taskId) {
        await this.cleanupSession(taskRunId);
      }
    }
  }

  async cancelPrompt(
    sessionId: string,
    reason?: InterruptReason,
  ): Promise<boolean> {
    const session = this.sessions.get(sessionId);
    if (!session) return false;

    try {
      this.cancelInFlightMcpToolCalls(session);
      await session.clientSideConnection.cancel({
        sessionId: getAgentSessionId(session),
        _meta: reason ? { interruptReason: reason } : undefined,
      });
      if (reason) {
        session.interruptReason = reason;
        this.log.info("Session interrupted", { sessionId, reason });
      }
      return true;
    } catch (err) {
      this.log.error("Failed to cancel prompt", { sessionId, err });
      return false;
    }
  }

  getSession(taskRunId: string): ManagedSession | undefined {
    return this.sessions.get(taskRunId);
  }

  getDebugSnapshot(): {
    sessions: Array<{
      taskRunId: string;
      taskId: string;
      repoPath: string;
      adapter: string;
      model: string | null;
      sessionId: string | null;
      channel: string;
      createdAt: number;
      lastActivityAt: number;
      promptPending: boolean;
      inFlightToolCalls: number;
      idleDeadline: number | null;
    }>;
    pendingPermissions: Array<{
      taskRunId: string;
      toolCallId: string;
    }>;
  } {
    const sessions = [...this.sessions.values()].map((session) => ({
      taskRunId: session.taskRunId,
      taskId: session.taskId,
      repoPath: session.repoPath,
      adapter: session.config.adapter ?? "claude",
      model: session.config.model ?? null,
      sessionId: session.config.sessionId ?? null,
      channel: session.channel,
      createdAt: session.createdAt,
      lastActivityAt: session.lastActivityAt,
      promptPending: session.promptPending,
      inFlightToolCalls: session.inFlightMcpToolCalls.size,
      idleDeadline: this.idleTimeouts.get(session.taskRunId)?.deadline ?? null,
    }));
    const pendingPermissions = [...this.pendingPermissions.values()].map(
      (perm) => ({
        taskRunId: perm.taskRunId,
        toolCallId: perm.toolCallId,
      }),
    );
    return { sessions, pendingPermissions };
  }

  async setSessionConfigOption(
    sessionId: string,
    configId: string,
    value: string,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    try {
      const result = await session.clientSideConnection.setSessionConfigOption({
        sessionId: getAgentSessionId(session),
        configId,
        value,
      });
      session.configOptions = result.configOptions ?? session.configOptions;

      const updatedModeOption = session.configOptions?.find(
        (opt) => opt.category === "mode",
      );
      if (
        updatedModeOption &&
        typeof updatedModeOption.currentValue === "string"
      ) {
        session.config.permissionMode = updatedModeOption.currentValue;
      }
    } catch (err) {
      this.log.error("Failed to set session config option", {
        sessionId,
        configId,
        value,
        err,
      });
      throw err;
    }
  }

  listSessions(taskId?: string): ManagedSession[] {
    const all = Array.from(this.sessions.values());
    return taskId ? all.filter((s) => s.taskId === taskId) : all;
  }

  /**
   * Resolve env-var overrides set by the SessionStart-style hooks of the most
   * recently active agent session for `taskId`.
   *
   * Used by git/gh operations triggered from the UI (Commit, Create PR) so
   * they pick up the same hook env the agent itself sees — most importantly
   * the SSH_AUTH_SOCK that Secretive's hook re-points at the Secretive agent
   * for commit signing. Returns an empty object when there is no session for
   * the task or when no hook output is available.
   */
  public async getSessionEnvForTask(
    taskId: string,
  ): Promise<Record<string, string>> {
    const candidates = this.listSessions(taskId)
      .filter((s) => !!s.config.sessionId)
      .sort((a, b) => b.lastActivityAt - a.lastActivityAt);
    const session = candidates[0];
    if (!session?.config.sessionId) return {};
    return loadSessionEnvOverrides(session.config.sessionId);
  }

  /**
   * Get sessions that were interrupted for a specific reason.
   * Optionally filter by repoPath to get only sessions for a specific repo.
   */
  getInterruptedSessions(
    reason: InterruptReason,
    repoPath?: string,
  ): ManagedSession[] {
    return Array.from(this.sessions.values()).filter(
      (s) =>
        s.interruptReason === reason &&
        (repoPath === undefined || s.repoPath === repoPath),
    );
  }

  /**
   * Resume an interrupted session by clearing the interrupt reason
   * and sending a continue prompt.
   */
  async resumeInterruptedSession(sessionId: string): Promise<PromptOutput> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }
    if (!session.interruptReason) {
      throw new Error(`Session ${sessionId} was not interrupted`);
    }
    this.log.info("Resuming interrupted session", {
      sessionId,
      reason: session.interruptReason,
    });
    // Clear the interrupt reason
    session.interruptReason = undefined;
    // Send a continue prompt
    return this.prompt(sessionId, [
      { type: "text", text: "Continue where you left off." },
    ]);
  }

  setPendingContext(taskRunId: string, context: string): void {
    const session = this.sessions.get(taskRunId);
    if (!session) {
      this.log.warn("Session not found for setPendingContext", { taskRunId });
      return;
    }
    session.pendingContext = context;
    this.log.info("Set pending context on session", {
      taskRunId,
      contextLength: context.length,
    });
  }

  /**
   * Notify a session of a context change (CWD moved, detached HEAD, etc).
   * Used when focusing/unfocusing worktrees - the agent doesn't need to respawn
   * because it has additionalDirectories configured, but it should know about the change.
   */
  async notifySessionContext(
    sessionId: string,
    context: import("./schemas.js").SessionContextChange,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      this.log.warn("Session not found for context notification", {
        sessionId,
      });
      return;
    }

    const contextMessage = this.buildContextMessage(context);

    // Check if session is currently busy
    if (session.promptPending) {
      // Active session: send immediately with continue instruction
      this.prompt(sessionId, [
        {
          type: "text",
          text: `${contextMessage} Continue where you left off.`,
          _meta: { ui: { hidden: true } },
        },
      ]);
    } else {
      // Idle session: store for prepending to next user message
      session.pendingContext = contextMessage;
    }

    this.log.info("Notified session of context change", {
      sessionId,
      context,
      wasPromptPending: session.promptPending,
    });
  }

  private buildContextMessage(
    context: import("./schemas.js").SessionContextChange,
  ): string {
    if (context.isDetached) {
      return `Your worktree is now on detached HEAD while the user edits in their main repo. The branch is \`${context.branchName}\`.

For git operations while detached:
- Commit: works normally
- Push: \`git push origin HEAD:refs/heads/${context.branchName}\`
- Pull: \`git fetch origin ${context.branchName} && git merge FETCH_HEAD\``;
    }
    return `Your worktree is back on branch \`${context.branchName}\`. Normal git commands work again.`;
  }

  @preDestroy()
  async cleanupAll(): Promise<void> {
    for (const { handle } of this.idleTimeouts.values()) clearTimeout(handle);
    this.idleTimeouts.clear();
    const sessionIds = Array.from(this.sessions.keys());
    this.log.info("Cleaning up all agent sessions", {
      sessionCount: sessionIds.length,
    });

    for (const session of this.sessions.values()) {
      try {
        await session.agent.flushAllLogs();
      } catch {
        this.log.debug("Failed to flush session logs during shutdown");
      }
    }

    for (const taskRunId of sessionIds) {
      await this.cleanupSession(taskRunId);
    }

    this.log.info("All agent sessions cleaned up");
  }

  private cancelInFlightMcpToolCalls(session: ManagedSession): void {
    for (const [toolCallId, toolKey] of session.inFlightMcpToolCalls) {
      this.mcpAppsService.notifyToolCancelled(toolKey, toolCallId);
    }

    session.inFlightMcpToolCalls.clear();
  }

  private async cleanupSession(taskRunId: string): Promise<void> {
    const session = this.sessions.get(taskRunId);
    if (session) {
      if (session.promptPending || session.inFlightMcpToolCalls.size > 0) {
        this.log.warn("Cleaning up session with in-flight work", {
          taskRunId,
          taskId: session.taskId,
          promptPending: session.promptPending,
          inFlightMcpToolCalls: session.inFlightMcpToolCalls.size,
        });
      }
      this.cancelInFlightMcpToolCalls(session);
      this.sleepService.release(taskRunId);
      try {
        await session.agent.cleanup();
      } catch {
        this.log.debug("Agent cleanup failed", { taskRunId });
      }

      await cleanupCodexHome(this.storagePaths.appDataPath, taskRunId).catch(
        () => this.log.debug("Codex home cleanup failed", { taskRunId }),
      );

      this.sessions.delete(taskRunId);

      const timeout = this.idleTimeouts.get(taskRunId);
      if (timeout) {
        clearTimeout(timeout.handle);
        this.idleTimeouts.delete(taskRunId);
      }

      // When no sessions remain, tear down MCP Apps connections and cached resources
      if (this.sessions.size === 0) {
        this.mcpAppsService.cleanup().catch(() => {
          this.log.debug("MCP Apps cleanup failed");
        });
      }
    }
  }

  private createClientConnection(
    taskRunId: string,
    _channel: string,
    clientStreams: { readable: ReadableStream; writable: WritableStream },
  ): ClientSideConnection {
    // Capture service reference for use in client callbacks
    const service = this;

    const emitToRenderer = (payload: unknown) => {
      // Emit event via TypedEventEmitter for tRPC subscription
      this.emit(AgentServiceEvent.SessionEvent, {
        taskRunId,
        payload,
      });
    };

    const onAcpMessage = (message: unknown) => {
      const acpMessage: AcpMessage = {
        type: "acp_message",
        ts: Date.now(),
        message: message as AcpMessage["message"],
      };
      emitToRenderer(acpMessage);

      // Inspect tool call updates for PR URLs and file activity
      this.handleToolCallUpdate(taskRunId, message as AcpMessage["message"]);
    };

    const tappedReadable = createTappedReadableStream(
      clientStreams.readable as ReadableStream<Uint8Array>,
      onAcpMessage,
      service.log,
    );

    const tappedWritable = createTappedWritableStream(
      clientStreams.writable as WritableStream<Uint8Array>,
      onAcpMessage,
      service.log,
    );

    const client: Client = {
      async requestPermission(
        params: RequestPermissionRequest,
      ): Promise<RequestPermissionResponse> {
        const toolName =
          (params.toolCall?.rawInput as { toolName?: string } | undefined)
            ?.toolName || "";
        const toolCallId = params.toolCall?.toolCallId || "";
        const codeToolKind = (
          params.toolCall?._meta as { codeToolKind?: string } | undefined
        )?.codeToolKind;

        service.log.info("requestPermission called", {
          taskRunId,
          toolCallId,
          toolName,
          title: params.toolCall?.title,
          optionCount: params.options.length,
        });

        const session = service.sessions.get(taskRunId);
        if (
          shouldAutoApprovePermissionRequest(
            session?.config.adapter,
            session?.config.permissionMode,
            codeToolKind,
          )
        ) {
          service.log.info("Auto-approving Codex full-access permission", {
            taskRunId,
            toolCallId,
          });
          return { outcome: buildAutoApproveOutcome(params.options) };
        }

        if (toolName && isMcpToolReadOnly(toolName)) {
          const approvalState = session?.mcpToolApprovals?.[toolName];
          if (approvalState === "approved") {
            service.log.info("Auto-approving read-only MCP tool", {
              taskRunId,
              toolName,
            });
            return { outcome: buildAutoApproveOutcome(params.options) };
          }
        }

        // If we have a toolCallId, always prompt the user for permission.
        // The claude.ts adapter only calls requestPermission when user input is needed.
        // (It handles auto-approve internally for acceptEdits/bypassPermissions modes)
        if (toolCallId) {
          service.sleepService.release(taskRunId);
          try {
            const response = await new Promise<RequestPermissionResponse>(
              (resolve, reject) => {
                const key = `${taskRunId}:${toolCallId}`;
                service.pendingPermissions.set(key, {
                  resolve,
                  reject,
                  taskRunId,
                  toolCallId,
                });

                service.log.info("Emitting permission request to renderer", {
                  taskRunId,
                  toolCallId,
                });
                const { sessionId: _agentSessionId, ...rest } = params;
                service.emit(AgentServiceEvent.PermissionRequest, {
                  ...rest,
                  taskRunId,
                });
              },
            );

            const approved =
              response.outcome?.outcome === "selected" &&
              (response.outcome.optionId === "allow" ||
                response.outcome.optionId === "allow_always");
            if (approved && toolName) {
              const session = service.sessions.get(taskRunId);
              if (
                session?.mcpToolApprovals?.[toolName] === "needs_approval" &&
                session.toolInstallations[toolName]
              ) {
                const { installationId, toolName: rawToolName } =
                  session.toolInstallations[toolName];
                try {
                  await service.agentAuthAdapter.updateMcpToolApproval(
                    session.config.credentials,
                    installationId,
                    rawToolName,
                    "approved",
                  );
                  session.mcpToolApprovals[toolName] = "approved";
                } catch (err) {
                  service.log.warn(
                    "Failed to update tool approval on backend",
                    {
                      toolName,
                      error: err instanceof Error ? err.message : String(err),
                    },
                  );
                }
              }
            }

            return response;
          } finally {
            // Only re-acquire if session wasn't cleaned up while waiting
            if (service.sessions.has(taskRunId)) {
              service.sleepService.acquire(taskRunId);
            }
          }
        }

        // Fallback: no toolCallId means we can't track the response, auto-approve
        service.log.warn(
          "No toolCallId in permission request, auto-approving",
          {
            taskRunId,
            toolName,
          },
        );
        return { outcome: buildAutoApproveOutcome(params.options) };
      },

      async readTextFile(params) {
        const session = service.sessions.get(taskRunId);
        if (!session) {
          throw new Error(`No active session for taskRunId=${taskRunId}`);
        }
        const repoPath = session.config.repoPath;
        const relativePath = service.toRepoRelativePath(repoPath, params.path);
        const content = await service.fsService.readRepoFile(
          repoPath,
          relativePath,
        );
        if (content === null) {
          throw new Error(`File not found: ${params.path}`);
        }
        return { content };
      },

      async writeTextFile(params) {
        const session = service.sessions.get(taskRunId);
        if (!session) {
          throw new Error(`No active session for taskRunId=${taskRunId}`);
        }
        const repoPath = session.config.repoPath;
        const relativePath = service.toRepoRelativePath(repoPath, params.path);
        await service.fsService.writeRepoFile(
          repoPath,
          relativePath,
          params.content,
        );
        return {};
      },

      async sessionUpdate(params: SessionNotification) {
        // Forward MCP tool events to McpAppsService using the SDK's
        // typed discriminated union instead of parsing raw JSON.
        const { update } = params;
        if (
          update.sessionUpdate !== "tool_call" &&
          update.sessionUpdate !== "tool_call_update"
        ) {
          return;
        }

        const toolName = (update._meta as ClaudeCodeToolMeta | undefined)
          ?.claudeCode?.toolName;
        if (!toolName?.startsWith("mcp__")) return;

        const session = service.sessions.get(taskRunId);
        if (update.sessionUpdate === "tool_call") {
          session?.inFlightMcpToolCalls.set(update.toolCallId, toolName);
          service.mcpAppsService.notifyToolInput(
            toolName,
            update.toolCallId,
            update.rawInput,
          );
        } else if (
          update.status === "completed" ||
          update.status === "failed"
        ) {
          session?.inFlightMcpToolCalls.delete(update.toolCallId);
          service.mcpAppsService.notifyToolResult(
            toolName,
            update.toolCallId,
            update.rawOutput,
            update.status === "failed",
          );
        }
      },

      extNotification: async (
        method: string,
        params: Record<string, unknown>,
      ): Promise<void> => {
        if (isNotification(method, POSTHOG_NOTIFICATIONS.SDK_SESSION)) {
          const {
            taskRunId: notifTaskRunId,
            sessionId,
            adapter: notifAdapter,
          } = params as {
            taskRunId: string;
            sessionId: string;
            adapter: Adapter;
          };
          const session = this.sessions.get(notifTaskRunId);
          if (session) {
            session.config.sessionId = sessionId;
            if (notifAdapter) {
              session.config.adapter = notifAdapter;
            }
            service.log.info("Session ID captured", {
              taskRunId: notifTaskRunId,
              sessionId,
              adapter: notifAdapter,
            });
          }
        }

        if (isNotification(method, POSTHOG_NOTIFICATIONS.USAGE_UPDATE)) {
          this.emit(AgentServiceEvent.LlmActivity, undefined);
        }

        // Extension notifications already flow through the tapped stream
        // (same pattern as sessionUpdate). No need to re-emit here.
      },
    };

    const clientStream = ndJsonStream(tappedWritable, tappedReadable);

    return new ClientSideConnection((_agent) => client, clientStream);
  }

  private validateSessionParams(
    params: StartSessionInput | ReconnectSessionInput,
  ): void {
    if (!params.taskId || !params.repoPath) {
      throw new Error("taskId and repoPath are required");
    }
    if (!params.apiHost) {
      throw new Error("PostHog API host is required");
    }
  }

  private toRepoRelativePath(repoPath: string, filePath: string): string {
    const normalize = (inputPath: string): string => {
      try {
        return fs.realpathSync(inputPath);
      } catch {
        return resolve(inputPath);
      }
    };

    const resolvedRepo = normalize(repoPath);
    const resolvedFile = isAbsolute(filePath)
      ? resolve(filePath)
      : resolve(repoPath, filePath);
    const resolvedFileForCheck = fs.existsSync(resolvedFile)
      ? normalize(resolvedFile)
      : resolve(resolvedFile);
    const repoPrefix = resolvedRepo.endsWith(sep)
      ? resolvedRepo
      : `${resolvedRepo}${sep}`;

    if (
      resolvedFileForCheck === resolvedRepo ||
      !resolvedFileForCheck.startsWith(repoPrefix)
    ) {
      throw new Error(`Access denied: path outside repository (${filePath})`);
    }

    return relative(resolvedRepo, resolvedFileForCheck);
  }

  private toSessionConfig(
    params: StartSessionInput | ReconnectSessionInput,
  ): SessionConfig {
    return {
      taskId: params.taskId,
      taskRunId: params.taskRunId,
      repoPath: params.repoPath,
      credentials: {
        apiHost: params.apiHost,
        projectId: params.projectId,
      },
      logUrl: "logUrl" in params ? params.logUrl : undefined,
      sessionId: "sessionId" in params ? params.sessionId : undefined,
      adapter: "adapter" in params ? params.adapter : undefined,
      permissionMode:
        "permissionMode" in params ? params.permissionMode : undefined,
      customInstructions:
        "customInstructions" in params ? params.customInstructions : undefined,
      systemPromptOverride:
        "systemPromptOverride" in params
          ? params.systemPromptOverride
          : undefined,
      disallowedTools:
        "disallowedTools" in params ? params.disallowedTools : undefined,
      effort: "effort" in params ? params.effort : undefined,
      model: "model" in params ? params.model : undefined,
      jsonSchema: "jsonSchema" in params ? params.jsonSchema : undefined,
      importedSessionId:
        "importedSessionId" in params ? params.importedSessionId : undefined,
      rtkEnabled: "rtkEnabled" in params ? params.rtkEnabled : undefined,
      spokenNarration:
        "spokenNarration" in params ? params.spokenNarration : undefined,
    };
  }

  private toSessionResponse(session: ManagedSession): SessionResponse {
    return {
      sessionId: session.taskRunId,
      channel: session.channel,
      configOptions: session.configOptions,
      steering: session.steering,
    };
  }

  private handleToolCallUpdate(taskRunId: string, message: unknown): void {
    try {
      const msg = message as {
        method?: string;
        params?: {
          update?: {
            sessionUpdate?: string;
            _meta?: {
              claudeCode?: {
                toolName?: string;
                toolResponse?: unknown;
                bashCommand?: string;
              };
            };
            content?: Array<{ type?: string; text?: string }>;
          };
        };
      };

      // Only process session/update notifications for tool_call_update
      if (msg.method !== "session/update") return;
      if (msg.params?.update?.sessionUpdate !== "tool_call_update") return;

      const update = msg.params.update;
      const session = this.sessions.get(taskRunId);

      // Runs before the toolName gate: a PR URL can surface without a Bash
      // toolName (e.g. in terminal output).
      this.maybeAttachCreatedPr(taskRunId, session, update);

      const toolMeta = update._meta?.claudeCode;
      const toolName = toolMeta?.toolName;
      if (!toolName) return;

      this.trackAgentFileActivity(taskRunId, session, toolName);
    } catch (err) {
      this.log.debug("Error in tool call update handling", {
        taskRunId,
        error: err,
      });
    }
  }

  private maybeAttachCreatedPr(
    taskRunId: string,
    session: ManagedSession | undefined,
    update: unknown,
  ): void {
    if (!session) return;
    for (const prUrl of findPrUrls(JSON.stringify(update))) {
      if (session.evaluatedPrUrls.has(prUrl)) continue;
      session.evaluatedPrUrls.add(prUrl);
      session.prAttachChain = session.prAttachChain
        .catch(() => {})
        .then(() => this.attachPrIfCreatedThisRun(taskRunId, session, prUrl));
    }
  }

  private async attachPrIfCreatedThisRun(
    taskRunId: string,
    session: ManagedSession,
    prUrl: string,
  ): Promise<void> {
    const [attribution, ghLogin] = await Promise.all([
      this.fetchPrAttribution(session.repoPath, prUrl),
      this.fetchGhLogin(session.repoPath),
    ]);
    if (!wasCreatedRecently(attribution.createdAt, Date.now())) return;
    if (!wasCreatedByLogin(attribution.author, ghLogin)) return;

    this.log.info("Detected PR URL created during run", { taskRunId, prUrl });

    try {
      await session.agent.attachPullRequestToTask(session.taskId, prUrl);
      this.log.info("PR URL attached to task", {
        taskRunId,
        taskId: session.taskId,
        prUrl,
      });
    } catch (err) {
      this.log.error("Failed to attach PR URL to task", {
        taskRunId,
        taskId: session.taskId,
        prUrl,
        error: err,
      });
    }

    // The user-initiated PR-creation flow links the current branch to the
    // workspace atomically (see GitService.createPr). PRs created via bash —
    // e.g. an agent running a `/commit-and-pr` skill — never go through that
    // flow, so `workspace.linkedBranch` would otherwise stay unset and
    // PR-aware UI (the unified PR badge, branch mismatch warning, diff
    // source) would have no anchor. Emit AgentFileActivity here too so
    // WorkspaceService.handleAgentFileActivity links the current feature
    // branch the moment we observe a PR for it.
    this.emitAgentFileActivityForCurrentBranch(taskRunId, session, {
      reason: "pr-detected",
    });
  }

  /** PR `createdAt` (ISO) and author login via the GitHub CLI; nulls if unresolvable. */
  private async fetchPrAttribution(
    cwd: string,
    prUrl: string,
  ): Promise<{ createdAt: string | null; author: string | null }> {
    try {
      const res = await execGh(
        ["pr", "view", prUrl, "--json", "createdAt,author"],
        {
          cwd,
          timeoutMs: 10_000,
        },
      );
      if (res.exitCode !== 0) return { createdAt: null, author: null };
      const data = JSON.parse(res.stdout) as {
        createdAt?: string;
        author?: { login?: string };
      };
      return {
        createdAt: data.createdAt ?? null,
        author: data.author?.login ?? null,
      };
    } catch (err) {
      this.log.debug("Failed to resolve PR attribution", { prUrl, error: err });
      return { createdAt: null, author: null };
    }
  }

  private ghLoginPromise: Promise<string | null> | null = null;

  private fetchGhLogin(cwd: string): Promise<string | null> {
    this.ghLoginPromise ??= execGh(["api", "user", "--jq", ".login"], {
      cwd,
      timeoutMs: 10_000,
    })
      .then((res) => {
        const login = res.exitCode === 0 ? res.stdout.trim() : "";
        if (!login) this.ghLoginPromise = null;
        return login || null;
      })
      .catch(() => {
        this.ghLoginPromise = null;
        return null;
      });
    return this.ghLoginPromise;
  }

  /**
   * Track agent file activity for branch association observability.
   */
  private static readonly FILE_MODIFYING_TOOLS = new Set([
    "Edit",
    "Write",
    "FileEditTool",
    "FileWriteTool",
    "MultiEdit",
    "NotebookEdit",
  ]);

  private trackAgentFileActivity(
    taskRunId: string,
    session: ManagedSession | undefined,
    toolName: string,
  ): void {
    if (!session) return;
    if (!AgentService.FILE_MODIFYING_TOOLS.has(toolName)) return;

    this.emitAgentFileActivityForCurrentBranch(taskRunId, session, {
      reason: "file-edit",
      toolName,
    });
  }

  /**
   * Resolve the current branch in the session's repo and emit AgentFileActivity
   * so WorkspaceService can link the branch to the task. Best-effort — branch
   * resolution failures are logged but never thrown.
   */
  private emitAgentFileActivityForCurrentBranch(
    taskRunId: string,
    session: ManagedSession,
    context: { reason: "file-edit" | "pr-detected"; toolName?: string },
  ): void {
    getCurrentBranch(session.repoPath)
      .then((branchName) => {
        this.emit(AgentServiceEvent.AgentFileActivity, {
          taskId: session.taskId,
          branchName,
        });
      })
      .catch((err) => {
        this.log.warn("Failed to emit agent file activity event", {
          taskRunId,
          taskId: session.taskId,
          ...context,
          error: err,
        });
      });
  }

  async getGatewayModels(apiHost: string) {
    const gatewayUrl = getLlmGatewayUrl(apiHost);
    const models = await fetchGatewayModels({
      gatewayUrl,
      authToken: (await this.agentAuthAdapter.gatewayAuthToken()) ?? undefined,
    });

    const mapped = models.map((model) => ({
      modelId: model.id,
      name: formatGatewayModelName(model),
      description: `Context: ${model.context_window.toLocaleString()} tokens`,
      provider: getProviderName(model.owned_by),
    }));

    return mapped.sort((a, b) => {
      const providerOrder = ["Anthropic", "OpenAI", "Gemini"];
      const aProviderIdx = providerOrder.indexOf(a.provider ?? "");
      const bProviderIdx = providerOrder.indexOf(b.provider ?? "");
      if (aProviderIdx !== bProviderIdx) {
        const aIdx = aProviderIdx === -1 ? 999 : aProviderIdx;
        const bIdx = bProviderIdx === -1 ? 999 : bProviderIdx;
        return aIdx - bIdx;
      }
      return (
        getClaudeModelRecency(a.modelId) - getClaudeModelRecency(b.modelId)
      );
    });
  }

  async getPreviewConfigOptions(
    apiHost: string,
    adapter: Adapter = "claude",
  ): Promise<SessionConfigOption[]> {
    const gatewayUrl = getLlmGatewayUrl(apiHost);
    // Authenticated so the gateway can mark plan-restricted models; falls
    // back to an anonymous fetch (everything allowed) without auth.
    const gatewayModels = await fetchGatewayModels({
      gatewayUrl,
      authToken: (await this.agentAuthAdapter.gatewayAuthToken()) ?? undefined,
    });

    // The Claude adapter can also drive Cloudflare `@cf/` models the gateway serves over its
    // Anthropic-Messages surface, so the preview/default-model path must offer them too — otherwise an
    // advertised `@cf/*` model is dropped here and the pre-session run falls back to Opus.
    const modelFilter =
      adapter === "codex"
        ? isOpenAIModel
        : (model: GatewayModel) =>
            isAnthropicModel(model) || isCloudflareModel(model);

    const adapterModels = gatewayModels.filter((model) => modelFilter(model));
    const modelOptions = adapterModels.map((model) => ({
      value: model.id,
      name: formatGatewayModelName(model),
      description: `Context: ${model.context_window.toLocaleString()} tokens`,
      // Locked models stay listed so the picker can gate them instead of
      // silently dropping them.
      ...(model.allowed ? {} : { _meta: restrictedModelMeta() }),
    }));

    // The gateway returns models in an arbitrary order. Sort Claude models
    // oldest-to-newest so the picker is deterministic and the newest model
    // lands at the end of the list, closest to the trigger.
    if (adapter === "claude") {
      modelOptions.sort(
        (a, b) =>
          getClaudeModelRecency(a.value) - getClaudeModelRecency(b.value),
      );
    }

    const defaultModel =
      adapter === "codex"
        ? (modelOptions.find((o) => o.value === DEFAULT_CODEX_MODEL)?.value ??
          modelOptions[0]?.value ??
          "")
        : DEFAULT_GATEWAY_MODEL;

    const preferredModelId = modelOptions.some((o) => o.value === defaultModel)
      ? defaultModel
      : (modelOptions[0]?.value ?? defaultModel);
    // Never preselect a model the org's plan can't use — it would 403 on the
    // first message.
    const resolvedModelId = pickAllowedModel(adapterModels, preferredModelId);

    if (!modelOptions.some((o) => o.value === resolvedModelId)) {
      modelOptions.unshift({
        value: resolvedModelId,
        name: resolvedModelId,
        description: "Custom model",
      });
    }

    const modes =
      adapter === "codex" ? getAvailableCodexModes() : getAvailableModes();
    const modeOptions = modes.map((mode) => ({
      value: mode.id,
      name: mode.name,
      description: mode.description ?? undefined,
    }));
    const defaultMode = adapter === "codex" ? "auto" : "plan";

    const configOptions: SessionConfigOption[] = [
      {
        id: "mode",
        name: "Approval Preset",
        type: "select",
        currentValue: defaultMode,
        options: modeOptions,
        category: "mode",
        description:
          "Choose an approval and sandboxing preset for your session",
      },
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: resolvedModelId,
        options: modelOptions,
        category: "model",
        description: "Choose which model Claude should use",
      },
    ];

    const effortOpts = getReasoningEffortOptions(adapter, resolvedModelId);
    if (effortOpts) {
      configOptions.push({
        id: adapter === "codex" ? "reasoning_effort" : "effort",
        name: adapter === "codex" ? "Reasoning Level" : "Effort",
        type: "select",
        currentValue: "high",
        options: effortOpts,
        category: "thought_level",
        description:
          adapter === "codex"
            ? "Controls how much reasoning effort the model uses"
            : "Controls how much effort Claude puts into its response",
      });
    }

    return configOptions;
  }
}
