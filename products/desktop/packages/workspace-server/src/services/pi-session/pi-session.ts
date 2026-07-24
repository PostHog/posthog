import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import type { PiRuntime } from "@posthog/agent/pi/runtime";
import type { PiModelOption } from "@posthog/agent/pi/types";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type AgentConversationEvent,
  type PiRuntimeHealth,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { TASK_METADATA_REPOSITORY } from "../../db/identifiers";
import type { ITaskMetadataRepository } from "../../db/repositories/task-metadata-repository";
import { PROCESS_TRACKING_SERVICE } from "../process-tracking/identifiers";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import { PI_RUNTIME_FACTORY, type PiRuntimeFactory } from "./identifiers";
import type { StartPiSessionInput } from "./schemas";

type PiPoolSessionState = "starting" | "idle" | "streaming";

interface PiPoolEntry {
  taskId: string;
  state: PiPoolSessionState;
  lastUsedAt: number;
}

export function selectPiPoolEvictionCandidate(
  entries: PiPoolEntry[],
  protectedTaskId?: string,
): string | null {
  const candidate = entries
    .filter(
      (entry) => entry.taskId !== protectedTaskId && entry.state === "idle",
    )
    .sort((left, right) => left.lastUsedAt - right.lastUsedAt)[0];

  return candidate?.taskId ?? null;
}

type PiSessionEvent = Parameters<Parameters<PiRpcClient["onEvent"]>[0]>[0];

interface PiSessionEvents {
  event: { taskId: string; event: AgentConversationEvent };
}

interface ManagedPiSession {
  client: PiRpcClient;
  runtime: PiRuntime;
  state: PiPoolSessionState;
  lastUsedAt: number;
  pid?: number;
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
    @inject(ROOT_LOGGER) rootLogger: RootLogger,
  ) {
    super();
    this.log = rootLogger.scope("pi-session");
  }

  async start(
    input: StartPiSessionInput,
  ): Promise<{ sessionFile: string | null; sessionId: string }> {
    return this.runExclusive(input.taskId, () => this.startLocked(input));
  }

  private async startLocked(
    input: StartPiSessionInput,
  ): Promise<{ sessionFile: string | null; sessionId: string }> {
    await this.stopLocked(input.taskId);

    const runtime = await this.runtimeFactory.create({
      cwd: input.cwd,
      model: input.model,
    });
    const client = runtime.client;
    const session = this.registerSession(input.taskId, runtime);

    return this.startSession(input.taskId, client, session, async () => {
      const state = await client.getState();

      if (!state.sessionFile) {
        throw new Error(
          "Pi did not create a native session file, even though we expected it to.",
        );
      }

      this.taskMetadataRepository.upsert(input.taskId, {
        piSessionFile: state.sessionFile,
      });

      await client.prompt(input.prompt);

      return {
        sessionFile: state.sessionFile,
        sessionId: state.sessionId,
      };
    });
  }

  async resume(input: { taskId: string; cwd: string }): Promise<void> {
    await this.runExclusive(input.taskId, () => this.resumeLocked(input));
  }

  private async resumeLocked(input: {
    taskId: string;
    cwd: string;
  }): Promise<void> {
    const existingSession = this.sessions.get(input.taskId);
    if (existingSession) {
      this.touchSession(existingSession);
      return;
    }

    const metadata = this.taskMetadataRepository.findByTaskId(input.taskId);
    const sessionFile = metadata?.piSessionFile;

    if (!sessionFile) {
      throw new Error(
        `Pi session metadata is missing for task ${input.taskId}`,
      );
    }

    await this.stopLocked(input.taskId);

    const runtime = await this.runtimeFactory.create({
      cwd: input.cwd,
      sessionFile,
    });
    const client = runtime.client;
    const session = this.registerSession(input.taskId, runtime);

    await this.startSession(input.taskId, client, session, async () => {});
  }

  async prompt(
    taskId: string,
    prompt: string,
    images?: Parameters<PiRpcClient["prompt"]>[1],
  ): Promise<void> {
    await this.requireSession(taskId).client.prompt(prompt, images);
  }

  async steer(
    taskId: string,
    message: string,
    images?: Parameters<PiRpcClient["steer"]>[1],
  ): Promise<void> {
    await this.requireSession(taskId).client.steer(message, images);
  }

  async followUp(
    taskId: string,
    message: string,
    images?: Parameters<PiRpcClient["followUp"]>[1],
  ): Promise<void> {
    await this.requireSession(taskId).client.followUp(message, images);
  }

  async abort(taskId: string): Promise<void> {
    await this.requireSession(taskId).client.abort();
  }

  async newSession(
    taskId: string,
    parentSession?: string,
  ): ReturnType<PiRpcClient["newSession"]> {
    const result =
      await this.requireSession(taskId).client.newSession(parentSession);

    if (!result.cancelled) {
      await this.persistSessionState(taskId);
    }

    return result;
  }

  setModel(
    taskId: string,
    provider: string,
    modelId: string,
  ): ReturnType<PiRpcClient["setModel"]> {
    return this.requireSession(taskId).client.setModel(provider, modelId);
  }

  cycleModel(taskId: string): ReturnType<PiRpcClient["cycleModel"]> {
    return this.requireSession(taskId).client.cycleModel();
  }

  availableModels(taskId: string): Promise<PiModelOption[]> {
    return this.requireSession(taskId).runtime.availableModels();
  }

  setThinkingLevel(
    taskId: string,
    level: Parameters<PiRpcClient["setThinkingLevel"]>[0],
  ): ReturnType<PiRpcClient["setThinkingLevel"]> {
    return this.requireSession(taskId).client.setThinkingLevel(level);
  }

  cycleThinkingLevel(
    taskId: string,
  ): ReturnType<PiRpcClient["cycleThinkingLevel"]> {
    return this.requireSession(taskId).client.cycleThinkingLevel();
  }

  setSteeringMode(
    taskId: string,
    mode: Parameters<PiRpcClient["setSteeringMode"]>[0],
  ): ReturnType<PiRpcClient["setSteeringMode"]> {
    return this.requireSession(taskId).client.setSteeringMode(mode);
  }

  setFollowUpMode(
    taskId: string,
    mode: Parameters<PiRpcClient["setFollowUpMode"]>[0],
  ): ReturnType<PiRpcClient["setFollowUpMode"]> {
    return this.requireSession(taskId).client.setFollowUpMode(mode);
  }

  compact(
    taskId: string,
    customInstructions?: string,
  ): ReturnType<PiRpcClient["compact"]> {
    return this.requireSession(taskId).client.compact(customInstructions);
  }

  setAutoCompaction(
    taskId: string,
    enabled: boolean,
  ): ReturnType<PiRpcClient["setAutoCompaction"]> {
    return this.requireSession(taskId).client.setAutoCompaction(enabled);
  }

  setAutoRetry(
    taskId: string,
    enabled: boolean,
  ): ReturnType<PiRpcClient["setAutoRetry"]> {
    return this.requireSession(taskId).client.setAutoRetry(enabled);
  }

  abortRetry(taskId: string): ReturnType<PiRpcClient["abortRetry"]> {
    return this.requireSession(taskId).client.abortRetry();
  }

  bash(taskId: string, command: string): ReturnType<PiRpcClient["bash"]> {
    return this.requireSession(taskId).client.bash(command);
  }

  abortBash(taskId: string): ReturnType<PiRpcClient["abortBash"]> {
    return this.requireSession(taskId).client.abortBash();
  }

  sessionStats(taskId: string): ReturnType<PiRpcClient["getSessionStats"]> {
    return this.requireSession(taskId).client.getSessionStats();
  }

  exportHtml(
    taskId: string,
    outputPath?: string,
  ): ReturnType<PiRpcClient["exportHtml"]> {
    return this.requireSession(taskId).client.exportHtml(outputPath);
  }

  async switchSession(
    taskId: string,
    sessionPath: string,
  ): ReturnType<PiRpcClient["switchSession"]> {
    const result =
      await this.requireSession(taskId).client.switchSession(sessionPath);

    if (!result.cancelled) {
      await this.persistSessionState(taskId);
    }

    return result;
  }

  async fork(taskId: string, entryId: string): ReturnType<PiRpcClient["fork"]> {
    const result = await this.requireSession(taskId).client.fork(entryId);

    if (!result.cancelled) {
      await this.persistSessionState(taskId);
    }

    return result;
  }

  async clone(taskId: string): ReturnType<PiRpcClient["clone"]> {
    const result = await this.requireSession(taskId).client.clone();

    if (!result.cancelled) {
      await this.persistSessionState(taskId);
    }

    return result;
  }

  forkMessages(taskId: string): ReturnType<PiRpcClient["getForkMessages"]> {
    return this.requireSession(taskId).client.getForkMessages();
  }

  tree(taskId: string): ReturnType<PiRpcClient["getTree"]> {
    return this.requireSession(taskId).client.getTree();
  }

  lastAssistantText(
    taskId: string,
  ): ReturnType<PiRpcClient["getLastAssistantText"]> {
    return this.requireSession(taskId).client.getLastAssistantText();
  }

  setSessionName(
    taskId: string,
    name: string,
  ): ReturnType<PiRpcClient["setSessionName"]> {
    return this.requireSession(taskId).client.setSessionName(name);
  }

  messages(taskId: string): ReturnType<PiRpcClient["getMessages"]> {
    return this.requireSession(taskId).client.getMessages();
  }

  commands(taskId: string): ReturnType<PiRpcClient["getCommands"]> {
    return this.requireSession(taskId).client.getCommands();
  }

  waitForIdle(
    taskId: string,
    timeout?: number,
  ): ReturnType<PiRpcClient["waitForIdle"]> {
    return this.requireSession(taskId).client.waitForIdle(timeout);
  }

  collectEvents(
    taskId: string,
    timeout?: number,
  ): ReturnType<PiRpcClient["collectEvents"]> {
    return this.requireSession(taskId).client.collectEvents(timeout);
  }

  promptAndWait(
    taskId: string,
    prompt: string,
    images?: Parameters<PiRpcClient["promptAndWait"]>[1],
    timeout?: number,
  ): ReturnType<PiRpcClient["promptAndWait"]> {
    return this.requireSession(taskId).client.promptAndWait(
      prompt,
      images,
      timeout,
    );
  }

  stderr(taskId: string): string {
    return this.requireSession(taskId).client.getStderr();
  }

  async stop(taskId: string): Promise<void> {
    await this.runExclusive(taskId, () => this.stopLocked(taskId));
  }

  private async stopLocked(taskId: string): Promise<void> {
    const session = this.sessions.get(taskId);

    if (!session) {
      return;
    }

    this.sessions.delete(taskId);

    try {
      await session.client.stop();
    } finally {
      if (session.pid) {
        this.processTracking.unregister(session.pid, "pi-session-stopped");
      }
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

  status(taskId: string): ReturnType<PiRpcClient["getState"]> {
    return this.requireSession(taskId).client.getState();
  }

  conversation(taskId: string): Promise<AgentConversationEvent[]> {
    return this.requireSession(taskId).runtime.conversation();
  }

  entries(
    taskId: string,
    since?: string,
  ): ReturnType<PiRpcClient["getEntries"]> {
    return this.requireSession(taskId).client.getEntries(since);
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
  ): ManagedPiSession {
    const session: ManagedPiSession = {
      client: runtime.client,
      runtime,
      state: "starting",
      lastUsedAt: Date.now(),
    };

    this.sessions.set(taskId, session);
    runtime.onRuntimeEvent((event) =>
      this.handleSessionEvent(taskId, session, event),
    );
    runtime.onConversationEvent((event) =>
      this.emit("event", { taskId, event }),
    );

    return session;
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
        })),
        protectedTaskId,
      );

      if (!taskId) {
        return;
      }
      this.log.info("Evicting least recently used Pi session", {
        taskId,
        maxHotSessions: this.maxHotSessions,
      });
      try {
        await this.stop(taskId);
      } catch (error) {
        this.log.warn("Failed to evict Pi session", { taskId, error });
        return;
      }
    }
  }
}
