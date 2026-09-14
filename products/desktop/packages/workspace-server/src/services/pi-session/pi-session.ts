import {
  buildSessionContext,
  type FileEntry,
  migrateSessionEntries,
  parseSessionEntries,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import type { RpcCommand, RpcResponse } from "@posthog/agent/pi/rpc-transport";
import type { PiRuntime } from "@posthog/agent/pi/runtime";
import {
  PI_THINKING_LEVELS,
  type PiExtensionEvent,
  type PiPersistedSessionConfig,
  type PiQueueSnapshot,
  type RpcExtensionUIResponse,
} from "@posthog/agent/pi/types";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type AgentConversationEvent,
  type McpToolPermissionDecision,
  type McpToolPermissionRequest,
  type PiRuntimeHealth,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { TASK_METADATA_REPOSITORY } from "../../db/identifiers";
import type { ITaskMetadataRepository } from "../../db/repositories/task-metadata-repository";
import { MCP_TOOL_POLICY_UPDATER } from "../agent/identifiers";
import type { McpToolPolicyUpdater } from "../agent/ports";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import { PI_RUNTIME_FACTORY, type PiRuntimeFactory } from "./identifiers";
import {
  piExtensionEventSchema,
  type ResumePiSessionInput,
  type StartPiSessionInput,
} from "./schemas";

type PiPoolSessionState = "starting" | "idle" | "streaming";

interface PiPoolEntry {
  taskId: string;
  state: PiPoolSessionState;
  lastUsedAt: number;
  activeRequestCount: number;
}

export function selectPiPoolEvictionCandidate(
  entries: PiPoolEntry[],
  protectedTaskId?: string,
): string | null {
  const candidate = entries
    .filter(
      (entry) =>
        entry.taskId !== protectedTaskId &&
        entry.state === "idle" &&
        entry.activeRequestCount === 0,
    )
    .sort((left, right) => left.lastUsedAt - right.lastUsedAt)[0];

  return candidate?.taskId ?? null;
}

type PiSessionEvent = Parameters<Parameters<PiRpcClient["onEvent"]>[0]>[0];

interface PiSessionEvents {
  event: { taskId: string; event: AgentConversationEvent };
  mcpPermissionRequest: {
    taskId: string;
    request: McpToolPermissionRequest;
  };
}

type PiExtensionDialogRequest = Extract<
  PiExtensionEvent,
  { method: "select" | "confirm" | "input" | "editor" }
>;

interface PiSessionExtensionEvents {
  event: PiExtensionEvent;
}

interface ManagedPiSession {
  client: PiRpcClient;
  pendingMcpPermissions: Map<string, McpToolPermissionRequest>;
  runtime: PiRuntime;
  cwd: string;
  state: PiPoolSessionState;
  lastUsedAt: number;
  activeRequestCount: number;
  stopFailed: boolean;
  extensionEventsAbort: AbortController;
  extensionEvents: TypedEventEmitter<PiSessionExtensionEvents>;
  startupExtensionDialogs: PiExtensionDialogRequest[];
  hasHadExtensionSubscriber: boolean;
  extensionSubscriberCount: number;
  outstandingExtensionDialogs: Set<string>;
  pid?: number;
}

function isPiExtensionDialogRequest(
  event: PiExtensionEvent,
): event is PiExtensionDialogRequest {
  return (
    event.type === "extension_ui_request" &&
    (event.method === "select" ||
      event.method === "confirm" ||
      event.method === "input" ||
      event.method === "editor")
  );
}

const DEFAULT_PI_HOT_POOL_SIZE = 4;

function readHotPoolSize(): number {
  const configured = Number.parseInt(
    process.env.POSTHOG_CODE_PI_HOT_POOL_SIZE ?? "",
    10,
  );

  if (!Number.isFinite(configured) || configured < 1) {
    return DEFAULT_PI_HOT_POOL_SIZE;
  }

  return configured;
}

@injectable()
export class PiSessionService extends TypedEventEmitter<PiSessionEvents> {
  private readonly sessions = new Map<string, ManagedPiSession>();
  private readonly lifecycleLocks = new Map<string, Promise<unknown>>();
  private readonly maxHotSessions = readHotPoolSize();
  private poolMaintenance: Promise<void> = Promise.resolve();
  private readonly log: ReturnType<RootLogger["scope"]>;

  constructor(
    @inject(PI_RUNTIME_FACTORY)
    private readonly runtimeFactory: PiRuntimeFactory,
    @inject(TASK_METADATA_REPOSITORY)
    private readonly taskMetadataRepository: ITaskMetadataRepository,
    @inject(PROCESS_TRACKING_SERVICE)
    private readonly processTracking: ProcessTrackingService,
    @inject(MCP_TOOL_POLICY_UPDATER)
    private readonly mcpToolPolicyUpdater: McpToolPolicyUpdater,
    @inject(ROOT_LOGGER) rootLogger: RootLogger,
  ) {
    super();
    this.log = rootLogger.scope("pi-session");
  }

  async start(
    input: StartPiSessionInput,
  ): Promise<{ sessionFile: string | null; sessionId: string }> {
    return this.runExclusive(input.taskContext.taskId, () =>
      this.startLocked(input),
    );
  }

  private async startLocked(
    input: StartPiSessionInput,
  ): Promise<{ sessionFile: string | null; sessionId: string }> {
    const { taskId, cwd } = input.taskContext;
    await this.stopLocked(taskId);

    const runtime = await this.runtimeFactory.create({
      taskContext: input.taskContext,
      model: input.model,
    });
    const client = runtime.client;
    const session = this.registerSession(taskId, runtime, cwd);

    return this.startSession(taskId, client, session, async () => {
      if (input.thinkingLevel) {
        await client.setThinkingLevel(input.thinkingLevel);
      }
      const state = await client.getState();

      if (!state.sessionFile) {
        throw new Error(
          "Pi did not create a native session file, even though we expected it to.",
        );
      }

      this.taskMetadataRepository.upsert(taskId, {
        piSessionFile: state.sessionFile,
      });

      await client.prompt(input.prompt);

      return {
        sessionFile: state.sessionFile,
        sessionId: state.sessionId,
      };
    });
  }

  async resume(input: ResumePiSessionInput): Promise<void> {
    await this.runExclusive(input.taskContext.taskId, () =>
      this.resumeLocked(input),
    );
  }

  private async resumeLocked(input: ResumePiSessionInput): Promise<void> {
    const { taskId, cwd } = input.taskContext;
    const existingSession = this.sessions.get(taskId);
    if (
      existingSession &&
      !existingSession.stopFailed &&
      existingSession.cwd === cwd
    ) {
      this.touchSession(existingSession);
      return;
    }

    const metadata = this.taskMetadataRepository.findByTaskId(taskId);
    const sessionFile = metadata?.piSessionFile;

    if (!sessionFile) {
      throw new Error(`Pi session metadata is missing for task ${taskId}`);
    }

    await this.stopLocked(taskId);

    const runtime = await this.runtimeFactory.create({
      taskContext: input.taskContext,
      sessionFile,
    });
    const client = runtime.client;
    const session = this.registerSession(taskId, runtime, cwd);

    await this.startSession(taskId, client, session, async () => {});
  }

  request(taskId: string, command: RpcCommand): Promise<RpcResponse> {
    return this.withActiveRequest(taskId, async (session) => {
      const response = await session.runtime.sendCommand(command);

      if (
        response.success &&
        ["new_session", "switch_session", "fork", "clone"].includes(
          command.type,
        )
      ) {
        await this.persistSessionState(taskId);
      }

      return response;
    });
  }

  getPendingMcpToolPermissions(taskId: string): McpToolPermissionRequest[] {
    const session = this.sessions.get(taskId);

    if (!session) {
      return [];
    }

    this.touchSession(session);
    return [...session.pendingMcpPermissions.values()];
  }

  async respondMcpToolPermission(
    taskId: string,
    request: McpToolPermissionRequest,
    decision: McpToolPermissionDecision,
  ): Promise<void> {
    const session = this.requireSession(taskId);
    const pending = session.pendingMcpPermissions.get(request.requestId);
    if (!pending) {
      throw new Error(`No pending MCP permission ${request.requestId}`);
    }
    if (decision === "allow_always") {
      await this.mcpToolPolicyUpdater.approveMcpTool(
        pending.installationId,
        pending.toolName,
      );
    }
    session.pendingMcpPermissions.delete(request.requestId);
    session.client.respondMcpToolPermission(request.requestId, decision);
  }

  getQueue(taskId: string): Promise<PiQueueSnapshot> {
    return this.withActiveRequest(taskId, (session) =>
      session.client.getQueue(),
    );
  }

  clearQueue(taskId: string): Promise<PiQueueSnapshot> {
    return this.withActiveRequest(taskId, async (session) => {
      const queue = await session.client.clearQueue();
      session.runtime.clearPendingQueuedUserMessages();
      return queue;
    });
  }

  respondToExtensionUI(
    taskId: string,
    response: RpcExtensionUIResponse,
  ): Promise<void> {
    return this.withActiveRequest(taskId, async (session) => {
      if (!session.outstandingExtensionDialogs.delete(response.id)) {
        return;
      }
      try {
        await session.client.respondToExtensionUI(response);
      } catch (error) {
        session.outstandingExtensionDialogs.add(response.id);
        throw error;
      }
    });
  }

  async *extensionEvents(
    taskId: string,
    signal?: AbortSignal,
  ): AsyncIterable<PiExtensionEvent> {
    const session = this.requireSession(taskId);
    const subscriptionAbort = new AbortController();
    const streamSignal = AbortSignal.any([
      ...(signal ? [signal] : []),
      session.extensionEventsAbort.signal,
      subscriptionAbort.signal,
    ]);

    if (streamSignal.aborted) {
      return;
    }

    const liveEvents = session.extensionEvents
      .toIterable("event", { signal: streamSignal })
      [Symbol.asyncIterator]();
    let nextLiveEvent = liveEvents.next();
    await Promise.resolve();
    session.hasHadExtensionSubscriber = true;
    session.extensionSubscriberCount += 1;

    try {
      for (const event of session.startupExtensionDialogs.splice(0)) {
        if (streamSignal.aborted || this.sessions.get(taskId) !== session) {
          return;
        }
        yield this.prepareExtensionEvent(event);
      }

      while (true) {
        const result = await nextLiveEvent;
        if (result.done) {
          return;
        }
        if (streamSignal.aborted || this.sessions.get(taskId) !== session) {
          return;
        }
        nextLiveEvent = liveEvents.next();
        yield this.prepareExtensionEvent(result.value);
      }
    } finally {
      session.extensionSubscriberCount -= 1;
      subscriptionAbort.abort();
      await liveEvents.return?.();
      if (
        session.extensionSubscriberCount === 0 &&
        this.sessions.get(taskId) === session
      ) {
        await this.cancelOutstandingExtensionDialogs(taskId, session);
      }
    }
  }

  async readSessionConfig(
    downloadUrl: string,
  ): Promise<PiPersistedSessionConfig | null> {
    const response = await fetch(downloadUrl, {
      signal: AbortSignal.timeout(30_000),
    });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(
        `Failed to download Pi task session: ${response.statusText}`,
      );
    }

    const fileEntries = parseSessionEntries(
      await response.text(),
    ) as FileEntry[];
    migrateSessionEntries(fileEntries);
    const entries = fileEntries.filter(
      (entry): entry is SessionEntry => entry.type !== "session",
    );
    const context = buildSessionContext(entries);
    const thinkingLevel = PI_THINKING_LEVELS.find(
      (level) => level === context.thinkingLevel,
    );

    return {
      model: context.model
        ? { provider: context.model.provider, id: context.model.modelId }
        : null,
      thinkingLevel: thinkingLevel ?? "off",
    };
  }

  async stop(taskId: string): Promise<void> {
    await this.runExclusive(taskId, () => this.stopLocked(taskId));
  }

  private async stopLocked(taskId: string): Promise<void> {
    const session = this.sessions.get(taskId);

    if (!session) {
      return;
    }

    try {
      await session.client.stop();
    } catch (error) {
      if (this.sessions.get(taskId) === session) {
        session.stopFailed = true;
        throw error;
      }
      return;
    }

    if (this.sessions.get(taskId) === session) {
      session.extensionEventsAbort.abort();
      this.sessions.delete(taskId);
    }
    if (session.pid) {
      this.processTracking.unregister(session.pid, "pi-session-stopped");
    }
  }

  health(taskId: string): PiRuntimeHealth {
    const session = this.sessions.get(taskId);

    if (!session) {
      return { state: "cold" };
    }

    return {
      state: session.state,
      pid: session.pid,
      lastUsedAt: session.lastUsedAt,
    };
  }

  async cleanup(): Promise<void> {
    await Promise.all(
      [...this.sessions.keys()].map((taskId) => this.stop(taskId)),
    );
  }

  private runExclusive<T>(
    taskId: string,
    operation: () => Promise<T>,
  ): Promise<T> {
    const previous = this.lifecycleLocks.get(taskId) ?? Promise.resolve();
    const result = previous.then(operation, operation);
    const tracked = result.then(
      () => undefined,
      () => undefined,
    );

    this.lifecycleLocks.set(taskId, tracked);
    void tracked.finally(() => {
      if (this.lifecycleLocks.get(taskId) === tracked) {
        this.lifecycleLocks.delete(taskId);
      }
    });

    return result;
  }

  private async startSession<T>(
    taskId: string,
    client: PiRpcClient,
    session: ManagedPiSession,
    initialize: () => Promise<T>,
  ): Promise<T> {
    try {
      await client.start();
      this.trackProcess(taskId, session);

      const state = await client.getState();
      session.state = state.isStreaming ? "streaming" : "idle";
      this.touchSession(session);

      const result = await initialize();
      await this.enforceHotPoolLimit(taskId);

      return result;
    } catch (error) {
      this.log.error("Failed to start Pi session", { taskId, error });

      await this.cleanupFailedClient(taskId, client);
      session.extensionEventsAbort.abort();
      this.sessions.delete(taskId);

      throw error;
    }
  }

  private async cleanupFailedClient(
    taskId: string,
    client: PiRpcClient,
  ): Promise<void> {
    try {
      await client.stop();
    } catch (error) {
      this.log.warn("Failed to stop Pi client after startup failure", {
        taskId,
        error,
      });
    }
  }

  private registerSession(
    taskId: string,
    runtime: PiRuntime,
    cwd: string,
  ): ManagedPiSession {
    const pendingMcpPermissions = new Map<string, McpToolPermissionRequest>();
    runtime.client.onMcpToolPermissionRequest((request) => {
      pendingMcpPermissions.set(request.requestId, request);
      this.emit("mcpPermissionRequest", { taskId, request });
    });

    const session: ManagedPiSession = {
      client: runtime.client,
      pendingMcpPermissions,
      runtime,
      cwd,
      state: "starting",
      lastUsedAt: Date.now(),
      activeRequestCount: 0,
      stopFailed: false,
      extensionEventsAbort: new AbortController(),
      extensionEvents: new TypedEventEmitter<PiSessionExtensionEvents>(),
      startupExtensionDialogs: [],
      hasHadExtensionSubscriber: false,
      extensionSubscriberCount: 0,
      outstandingExtensionDialogs: new Set(),
    };

    this.sessions.get(taskId)?.extensionEventsAbort.abort();
    this.sessions.set(taskId, session);
    runtime.onRuntimeEvent((event) =>
      this.handleSessionEvent(taskId, session, event),
    );
    runtime.onConversationEvent((event) =>
      this.emit("event", { taskId, event }),
    );
    runtime.onExtensionEvent?.((event) => {
      if (this.sessions.get(taskId) !== session) {
        return;
      }
      if (isPiExtensionDialogRequest(event)) {
        session.outstandingExtensionDialogs.add(event.id);
        if (session.extensionSubscriberCount === 0) {
          if (!session.hasHadExtensionSubscriber) {
            session.startupExtensionDialogs.push(event);
          } else {
            session.outstandingExtensionDialogs.delete(event.id);
            void session.client
              .respondToExtensionUI({
                type: "extension_ui_response",
                id: event.id,
                cancelled: true,
              })
              .catch((error) => {
                session.outstandingExtensionDialogs.add(event.id);
                this.log.warn("Failed to cancel orphaned Pi extension dialog", {
                  taskId,
                  requestId: event.id,
                  error,
                });
              });
          }
          return;
        }
      }
      session.extensionEvents.emit("event", event);
    });

    return session;
  }

  private prepareExtensionEvent(event: PiExtensionEvent): PiExtensionEvent {
    return piExtensionEventSchema.parse(event);
  }

  private async cancelOutstandingExtensionDialogs(
    taskId: string,
    session: ManagedPiSession,
  ): Promise<void> {
    const requestIds = [...session.outstandingExtensionDialogs];
    session.outstandingExtensionDialogs.clear();
    await Promise.all(
      requestIds.map(async (requestId) => {
        try {
          await session.client.respondToExtensionUI({
            type: "extension_ui_response",
            id: requestId,
            cancelled: true,
          });
        } catch (error) {
          session.outstandingExtensionDialogs.add(requestId);
          this.log.warn("Failed to cancel orphaned Pi extension dialog", {
            taskId,
            requestId,
            error,
          });
        }
      }),
    );
  }

  private trackProcess(taskId: string, session: ManagedPiSession): void {
    const process = session.runtime.process;

    if (!process?.pid) {
      return;
    }

    session.pid = process.pid;
    this.processTracking.register(
      process.pid,
      "agent",
      "pi-rpc",
      undefined,
      taskId,
    );

    process.once("exit", (code, signal) => {
      this.processTracking.unregister(process.pid as number, "pi-rpc-exit");

      if (this.sessions.get(taskId) !== session) {
        return;
      }

      session.extensionEventsAbort.abort();
      this.sessions.delete(taskId);
      this.log.warn("Pi RPC process exited", { taskId, code, signal });
    });
  }

  private async persistSessionState(taskId: string): Promise<void> {
    const state = await this.requireSession(taskId).client.getState();

    this.taskMetadataRepository.upsert(taskId, {
      piSessionFile: state.sessionFile ?? null,
    });
  }

  private async withActiveRequest<T>(
    taskId: string,
    operation: (session: ManagedPiSession) => Promise<T>,
  ): Promise<T> {
    const session = this.requireSession(taskId);
    session.activeRequestCount += 1;

    try {
      return await operation(session);
    } finally {
      session.activeRequestCount -= 1;
      void this.enforceHotPoolLimit();
    }
  }

  private requireSession(taskId: string): ManagedPiSession {
    const session = this.sessions.get(taskId);

    if (!session) {
      throw new Error(`Pi session not found for task ${taskId}`);
    }

    this.touchSession(session);
    return session;
  }

  private touchSession(session: ManagedPiSession): void {
    session.lastUsedAt = Date.now();
  }

  private handleSessionEvent(
    taskId: string,
    session: ManagedPiSession,
    event: PiSessionEvent,
  ): void {
    if (this.sessions.get(taskId) !== session) {
      return;
    }

    this.touchSession(session);

    if (event.type === "agent_start") {
      session.state = "streaming";
    } else if (event.type === "agent_settled") {
      session.state = "idle";
      void this.enforceHotPoolLimit();
    }
  }

  private enforceHotPoolLimit(protectedTaskId?: string): Promise<void> {
    const operation = this.poolMaintenance.then(() =>
      this.evictLeastRecentlyUsedSessions(protectedTaskId),
    );

    this.poolMaintenance = operation.catch(() => undefined);
    return operation;
  }

  private async evictLeastRecentlyUsedSessions(
    protectedTaskId?: string,
  ): Promise<void> {
    while (this.sessions.size > this.maxHotSessions) {
      const taskId = selectPiPoolEvictionCandidate(
        [...this.sessions.entries()].map(([taskId, session]) => ({
          taskId,
          state: session.state,
          lastUsedAt: session.lastUsedAt,
          activeRequestCount: session.activeRequestCount,
        })),
        protectedTaskId,
      );

      if (!taskId) {
        return;
      }
      try {
        await this.runExclusive(taskId, async () => {
          const session = this.sessions.get(taskId);
          const isEvictable =
            session?.state === "idle" && session.activeRequestCount === 0;

          if (!isEvictable || taskId === protectedTaskId) {
            return;
          }

          this.log.info("Evicting least recently used Pi session", {
            taskId,
            maxHotSessions: this.maxHotSessions,
          });
          await this.stopLocked(taskId);
        });
      } catch (error) {
        this.log.warn("Failed to evict Pi session", { taskId, error });
        return;
      }
    }
  }
}
