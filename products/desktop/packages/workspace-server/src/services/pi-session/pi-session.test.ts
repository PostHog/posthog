import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import type { RpcCommand, RpcResponse } from "@posthog/agent/pi/rpc-transport";
import type { PiRuntime } from "@posthog/agent/pi/runtime";
import type { PiExtensionEvent } from "@posthog/agent/pi/types";
import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
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
      { approveMcpTool: vi.fn() },
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
      onMcpToolPermissionRequest: vi.fn(),
      respondMcpToolPermission: vi.fn(),
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
    const mcpToolPolicyUpdater = { approveMcpTool: vi.fn() };
    const service = new PiSessionService(
      runtimeFactory,
      taskMetadataRepository,
      processTracking,
      mcpToolPolicyUpdater,
      rootLogger,
    );

    expect(service.getPendingMcpToolPermissions("task-1")).toEqual([]);

    await service.start({
      taskContext: {
        taskId: "task-1",
        cwd: "/tmp",
        customInstructions: "Keep the patch small.",
        additionalDirectories: ["/tmp/shared"],
        channelMode: true,
      },
      prompt: "hello",
      thinkingLevel: "high",
    });

    expect(runtimeFactory.create).toHaveBeenCalledWith({
      taskContext: {
        taskId: "task-1",
        cwd: "/tmp",
        customInstructions: "Keep the patch small.",
        additionalDirectories: ["/tmp/shared"],
        channelMode: true,
      },
      model: undefined,
    });
    expect(setThinkingLevel).toHaveBeenCalledWith("high");
    expect(setThinkingLevel.mock.invocationCallOrder[0]).toBeLessThan(
      prompt.mock.invocationCallOrder[0],
    );

    const request = {
      requestId: "call-1",
      serverName: "Cloudflare",
      toolName: "search",
      installationId: "installation-1",
      arguments: { query: "workers" },
    };
    const onRequest = (
      client.onMcpToolPermissionRequest as ReturnType<typeof vi.fn>
    ).mock.calls[0]?.[0];
    onRequest(request);
    expect(service.getPendingMcpToolPermissions("task-1")).toEqual([request]);
    await service.respondMcpToolPermission("task-1", request, "allow");

    expect(mcpToolPolicyUpdater.approveMcpTool).not.toHaveBeenCalled();
    expect(client.respondMcpToolPermission).toHaveBeenCalledWith(
      "call-1",
      "allow",
    );

    const persistentRequest = { ...request, requestId: "call-2" };
    onRequest(persistentRequest);
    await service.respondMcpToolPermission(
      "task-1",
      persistentRequest,
      "allow_always",
    );

    expect(mcpToolPolicyUpdater.approveMcpTool).toHaveBeenCalledWith(
      "installation-1",
      "search",
    );
    expect(client.respondMcpToolPermission).toHaveBeenCalledWith(
      "call-2",
      "allow_always",
    );
  });
});

describe("PiSessionService extension UI", () => {
  it("streams current-session extension events and forwards responses", async () => {
    const extensionHandlers: Array<(event: PiExtensionEvent) => void> = [];
    const clients = Array.from({ length: 2 }, (_, index) => ({
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: `/tmp/session-${index}.jsonl`,
        sessionId: `session-${index}`,
      }),
      onMcpToolPermissionRequest: vi.fn(),
      prompt: vi.fn().mockResolvedValue(undefined),
      respondToExtensionUI: vi.fn().mockResolvedValue(undefined),
    })) as unknown as PiRpcClient[];
    let runtimeIndex = 0;
    const runtimeFactory = {
      create: vi.fn(async () => {
        const client = clients[runtimeIndex++];
        return {
          client,
          process: undefined,
          onRuntimeEvent: vi.fn(),
          onConversationEvent: vi.fn(),
          onExtensionEvent: vi.fn((handler) => {
            extensionHandlers.push(handler);
            return () => {};
          }),
        };
      }),
    } as unknown as PiRuntimeFactory;
    const service = new PiSessionService(
      runtimeFactory,
      { upsert: vi.fn() } as unknown as ITaskMetadataRepository,
      {
        register: vi.fn(),
        unregister: vi.fn(),
      } as unknown as ProcessTrackingService,
      { approveMcpTool: vi.fn() },
      rootLogger,
    );
    const abortController = new AbortController();
    await service.start({
      taskContext: { taskId: "task-1", cwd: "/tmp" },
      prompt: "hello",
    });
    extensionHandlers[0]({
      type: "extension_ui_request",
      id: "startup-notification",
      method: "notify",
      message: "Ephemeral startup notification",
    });
    const startupRequest: PiExtensionEvent = {
      type: "extension_ui_request",
      id: "startup-extension",
      method: "confirm",
      title: "Continue?",
      message: "Run the startup extension?",
    };
    extensionHandlers[0](startupRequest);

    const iterator = service
      .extensionEvents("task-1", abortController.signal)
      [Symbol.asyncIterator]();
    await expect(iterator.next()).resolves.toEqual({
      done: false,
      value: startupRequest,
    });

    const firstEvent = iterator.next();
    const request: PiExtensionEvent = {
      ...startupRequest,
      id: "extension-1",
      message: "Run the extension?",
    };
    extensionHandlers[0](request);

    await expect(firstEvent).resolves.toEqual({ done: false, value: request });

    const response = {
      type: "extension_ui_response" as const,
      id: "extension-1",
      confirmed: true,
    };
    await service.respondToExtensionUI("task-1", response);
    expect(clients[0].respondToExtensionUI).toHaveBeenCalledWith(response);

    const pendingEvent = iterator.next();
    const pendingRequest = { ...request, id: "pending-extension" };
    extensionHandlers[0](pendingRequest);
    await expect(pendingEvent).resolves.toEqual({
      done: false,
      value: pendingRequest,
    });
    const queuedRequest = { ...request, id: "queued-extension" };
    extensionHandlers[0](queuedRequest);
    await iterator.return?.();
    await vi.waitFor(() => {
      expect(clients[0].respondToExtensionUI).toHaveBeenCalledWith({
        type: "extension_ui_response",
        id: pendingRequest.id,
        cancelled: true,
      });
      expect(clients[0].respondToExtensionUI).toHaveBeenCalledWith({
        type: "extension_ui_response",
        id: queuedRequest.id,
        cancelled: true,
      });
    });

    const orphanedRequest = { ...request, id: "orphaned-extension" };
    extensionHandlers[0](orphanedRequest);
    await vi.waitFor(() =>
      expect(clients[0].respondToExtensionUI).toHaveBeenCalledWith({
        type: "extension_ui_response",
        id: orphanedRequest.id,
        cancelled: true,
      }),
    );

    const oldIterator = service
      .extensionEvents("task-1", abortController.signal)
      [Symbol.asyncIterator]();
    const oldEvent = oldIterator.next();
    extensionHandlers[0]({ ...request, id: "buffered-old-extension" });
    await service.start({
      taskContext: { taskId: "task-1", cwd: "/tmp/replacement" },
      prompt: "hello again",
    });
    await expect(oldEvent).resolves.toEqual({
      done: true,
      value: undefined,
    });

    const replacementRequest: PiExtensionEvent = {
      ...request,
      id: "extension-2",
    };
    const replacementIterator = service
      .extensionEvents("task-1", abortController.signal)
      [Symbol.asyncIterator]();
    const replacementEvent = replacementIterator.next();
    extensionHandlers[0]({ ...request, id: "stale-extension" });
    extensionHandlers[1](replacementRequest);

    await expect(replacementEvent).resolves.toEqual({
      done: false,
      value: replacementRequest,
    });

    abortController.abort();
    await replacementIterator.return?.();
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
      onMcpToolPermissionRequest: vi.fn(),
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
      onMcpToolPermissionRequest: vi.fn(),
    } as unknown as PiRpcClient;
    const thirdClient = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue(undefined),
      getState: vi.fn().mockResolvedValue({
        isStreaming: false,
        sessionFile: "/tmp/third.jsonl",
      }),
      send: vi.fn(),
      onMcpToolPermissionRequest: vi.fn(),
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
      { approveMcpTool: vi.fn() },
      rootLogger,
    );

    await service.resume({
      taskContext: { taskId: "first", cwd: "/tmp" },
    });
    const bashRequest = service.request("first", {
      type: "bash",
      command: "sleep 1",
    });
    const queueRequest = service.getQueue("first");

    await service.resume({
      taskContext: { taskId: "second", cwd: "/tmp" },
    });
    expect(firstClient.stop).not.toHaveBeenCalled();

    requestResolvers[0](successfulResponse("bash"));
    await bashRequest;
    await vi.waitFor(() => expect(secondClient.stop).toHaveBeenCalledOnce());
    expect(firstClient.stop).not.toHaveBeenCalled();

    resolveQueue({ steering: [], followUp: [] });
    await queueRequest;
    expect(firstClient.stop).not.toHaveBeenCalled();

    await service.resume({
      taskContext: { taskId: "third", cwd: "/tmp" },
    });
    expect(firstClient.stop).toHaveBeenCalledOnce();
    expect(thirdClient.stop).not.toHaveBeenCalled();
  });
});
