import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import type { RpcCommand, RpcResponse } from "@posthog/agent/pi/rpc-transport";
import type { PiRuntime } from "@posthog/agent/pi/runtime";
import type { RootLogger } from "@posthog/di/logger";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ITaskMetadataRepository } from "../../db/repositories/task-metadata-repository";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import type { PiRuntimeFactory } from "./identifiers";
import { PiSessionService, selectPiPoolEvictionCandidate } from "./pi-session";

const scopedLogger = {
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};
const rootLogger: RootLogger = {
  ...scopedLogger,
  scope: () => scopedLogger,
};

function successfulResponse(command: string): RpcResponse {
  return {
    type: "response",
    command,
    success: true,
  } as RpcResponse;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("selectPiPoolEvictionCandidate", () => {
  it("selects the least recently used idle session", () => {
    expect(
      selectPiPoolEvictionCandidate([
        {
          taskId: "recent",
          state: "idle",
          lastUsedAt: 30,
          activeRequestCount: 0,
        },
        {
          taskId: "oldest",
          state: "idle",
          lastUsedAt: 10,
          activeRequestCount: 0,
        },
        {
          taskId: "middle",
          state: "idle",
          lastUsedAt: 20,
          activeRequestCount: 0,
        },
      ]),
    ).toBe("oldest");
  });

  it("pins streaming, starting, protected, and requested sessions", () => {
    expect(
      selectPiPoolEvictionCandidate(
        [
          {
            taskId: "streaming",
            state: "streaming",
            lastUsedAt: 1,
            activeRequestCount: 0,
          },
          {
            taskId: "starting",
            state: "starting",
            lastUsedAt: 2,
            activeRequestCount: 0,
          },
          {
            taskId: "requested",
            state: "idle",
            lastUsedAt: 3,
            activeRequestCount: 1,
          },
          {
            taskId: "protected",
            state: "idle",
            lastUsedAt: 4,
            activeRequestCount: 0,
          },
          {
            taskId: "evictable",
            state: "idle",
            lastUsedAt: 5,
            activeRequestCount: 0,
          },
        ],
        "protected",
      ),
    ).toBe("evictable");
  });

  it("returns null when every session is pinned", () => {
    expect(
      selectPiPoolEvictionCandidate([
        {
          taskId: "streaming",
          state: "streaming",
          lastUsedAt: 1,
          activeRequestCount: 0,
        },
        {
          taskId: "starting",
          state: "starting",
          lastUsedAt: 2,
          activeRequestCount: 0,
        },
        {
          taskId: "requested",
          state: "idle",
          lastUsedAt: 3,
          activeRequestCount: 2,
        },
      ]),
    ).toBeNull();
  });
});

describe("PiSessionService task session config", () => {
  it("uses Pi session context resolution for model and thinking", async () => {
    const content = [
      {
        type: "session",
        version: 3,
        id: "session-1",
        timestamp: "2026-01-01T00:00:00.000Z",
        cwd: "/repo",
      },
      {
        type: "model_change",
        id: "model-1",
        parentId: null,
        timestamp: "2026-01-01T00:00:01.000Z",
        provider: "posthog",
        modelId: "claude-opus-4-8",
      },
      {
        type: "thinking_level_change",
        id: "thinking-1",
        parentId: "model-1",
        timestamp: "2026-01-01T00:00:02.000Z",
        thinkingLevel: "high",
      },
    ]
      .map((entry) => JSON.stringify(entry))
      .join("\n");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(content)),
    );
    const service = new PiSessionService(
      {} as PiRuntimeFactory,
      {} as ITaskMetadataRepository,
      {} as ProcessTrackingService,
      rootLogger,
    );

    await expect(
      service.readSessionConfig("https://storage.example/session.jsonl"),
    ).resolves.toEqual({
      model: { provider: "posthog", id: "claude-opus-4-8" },
      thinkingLevel: "high",
    });
  });
});

describe("PiSessionService start", () => {
  it("sets the selected thinking level before the initial prompt", async () => {
    const setThinkingLevel = vi.fn().mockResolvedValue(undefined);
    const prompt = vi.fn().mockResolvedValue(undefined);
    const client = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: "/tmp/session.jsonl",
        sessionId: "session-1",
      }),
      setThinkingLevel,
      prompt,
    } as unknown as PiRpcClient;
    const runtimeFactory = {
      create: vi.fn(async () => ({
        client,
        process: undefined,
        onRuntimeEvent: vi.fn(),
        onConversationEvent: vi.fn(),
      })),
    } as unknown as PiRuntimeFactory;
    const taskMetadataRepository = {
      upsert: vi.fn(),
    } as unknown as ITaskMetadataRepository;
    const processTracking = {
      register: vi.fn(),
      unregister: vi.fn(),
    } as unknown as ProcessTrackingService;
    const service = new PiSessionService(
      runtimeFactory,
      taskMetadataRepository,
      processTracking,
      rootLogger,
    );

    await service.start({
      taskId: "task-1",
      cwd: "/tmp",
      prompt: "hello",
      thinkingLevel: "high",
    });

    expect(setThinkingLevel).toHaveBeenCalledWith("high");
    expect(setThinkingLevel.mock.invocationCallOrder[0]).toBeLessThan(
      prompt.mock.invocationCallOrder[0],
    );
  });
});

describe("PiSessionService RPC request pinning", () => {
  it("keeps a session pinned until command and queue requests settle", async () => {
    vi.stubEnv("POSTHOG_CODE_PI_HOT_POOL_SIZE", "1");
    let timestamp = 0;
    vi.spyOn(Date, "now").mockImplementation(() => timestamp++);

    const requestResolvers: Array<(response: RpcResponse) => void> = [];
    let resolveQueue: (queue: {
      steering: string[];
      followUp: string[];
    }) => void = () => {};
    const firstClient = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: "/tmp/first.jsonl",
      }),
      send: vi.fn(
        () =>
          new Promise<RpcResponse>((resolve) => {
            requestResolvers.push(resolve);
          }),
      ),
      getQueue: vi.fn(
        () =>
          new Promise<{ steering: string[]; followUp: string[] }>((resolve) => {
            resolveQueue = resolve;
          }),
      ),
    } as unknown as PiRpcClient;
    const secondClient = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: "/tmp/second.jsonl",
      }),
      send: vi.fn(),
    } as unknown as PiRpcClient;
    const thirdClient = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: "/tmp/third.jsonl",
      }),
      send: vi.fn(),
    } as unknown as PiRpcClient;
    const clients = [firstClient, secondClient, thirdClient];
    const runtimeFactory = {
      create: vi.fn(async () => {
        const client = clients.shift() as PiRpcClient;
        return {
          client,
          process: undefined,
          sendCommand: vi.fn((command) =>
            (
              client as unknown as {
                send(command: RpcCommand): Promise<RpcResponse>;
              }
            ).send(command),
          ),
          onRuntimeEvent: vi.fn(),
          onConversationEvent: vi.fn(),
        } as unknown as PiRuntime;
      }),
    } as PiRuntimeFactory;
    const taskMetadataRepository = {
      findByTaskId: vi.fn((taskId: string) => ({
        piSessionFile: `/tmp/${taskId}.jsonl`,
      })),
      upsert: vi.fn(),
    } as unknown as ITaskMetadataRepository;
    const processTracking = {
      register: vi.fn(),
      unregister: vi.fn(),
    } as unknown as ProcessTrackingService;
    const service = new PiSessionService(
      runtimeFactory,
      taskMetadataRepository,
      processTracking,
      rootLogger,
    );

    await service.resume({ taskId: "first", cwd: "/tmp" });
    const bashRequest = service.request("first", {
      type: "bash",
      command: "sleep 1",
    });
    const queueRequest = service.getQueue("first");

    await service.resume({ taskId: "second", cwd: "/tmp" });
    expect(firstClient.stop).not.toHaveBeenCalled();

    requestResolvers[0](successfulResponse("bash"));
    await bashRequest;
    await vi.waitFor(() => expect(secondClient.stop).toHaveBeenCalledOnce());
    expect(firstClient.stop).not.toHaveBeenCalled();

    resolveQueue({ steering: [], followUp: [] });
    await queueRequest;
    expect(firstClient.stop).not.toHaveBeenCalled();

    await service.resume({ taskId: "third", cwd: "/tmp" });
    expect(firstClient.stop).toHaveBeenCalledOnce();
    expect(thirdClient.stop).not.toHaveBeenCalled();
  });
});
