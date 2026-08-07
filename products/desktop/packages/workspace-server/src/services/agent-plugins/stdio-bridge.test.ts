import type { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";
import type { RootLogger } from "@posthog/di/logger";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProcessTrackingService } from "../process-tracking/process-tracking";
import {
  type AgentPluginStdioBridgeRegistration,
  AgentPluginStdioBridgeService,
  STDIO_BRIDGE_MARKER_HEADER,
  STDIO_BRIDGE_PROBE_HEADER,
} from "./stdio-bridge";

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

class FakeStdioTransport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  readonly stderr = null;
  readonly pid: number;
  readonly close = vi.fn(async () => {
    this.onclose?.();
  });
  readonly start = vi.fn(async () => {
    if (this.failStart) throw new Error("spawn failed");
  });
  readonly send = vi.fn(async (message: JSONRPCMessage) => {
    if (!("id" in message)) return;
    const id = message.id;
    if (typeof id !== "string" && typeof id !== "number") return;
    this.onmessage?.({
      jsonrpc: "2.0",
      id,
      result:
        "method" in message && message.method === "initialize"
          ? {
              protocolVersion: "2025-06-18",
              capabilities: {},
              serverInfo: { name: "test-server", version: "1.0.0" },
            }
          : {},
    });
  });

  constructor(
    pid: number,
    private readonly failStart: boolean,
  ) {
    this.pid = pid;
  }
}

class TestBridge extends AgentPluginStdioBridgeService {
  readonly transports: FakeStdioTransport[] = [];
  private nextPid = 1000;

  protected override createStdioTransport(
    registration: AgentPluginStdioBridgeRegistration,
  ): StdioClientTransport {
    const transport = new FakeStdioTransport(
      this.nextPid++,
      registration.command === "fail",
    );
    this.transports.push(transport);
    return transport as unknown as StdioClientTransport;
  }
}

function registration(
  id: string,
  overrides: Partial<AgentPluginStdioBridgeRegistration> = {},
): AgentPluginStdioBridgeRegistration {
  return {
    id,
    runId: "run-1",
    installationId: "installation-1",
    runtimeName: id,
    command: "node",
    args: [],
    env: { PLUGIN_ROOT: "/plugin", PLUGIN_DATA: "/data" },
    cwd: "/plugin",
    onFailure: vi.fn(),
    ...overrides,
  };
}

async function request(
  url: string,
  method: string,
  probe = false,
): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: {
      accept: "application/json, text/event-stream",
      "content-type": "application/json",
      [STDIO_BRIDGE_MARKER_HEADER]: "1",
      ...(probe ? { [STDIO_BRIDGE_PROBE_HEADER]: "1" } : {}),
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method,
      params:
        method === "initialize"
          ? {
              protocolVersion: "2025-06-18",
              capabilities: {},
              clientInfo: { name: "test", version: "1.0.0" },
            }
          : {},
    }),
  });
}

async function initialize(url: string, probe = false): Promise<Response> {
  return request(url, "initialize", probe);
}

describe("Agent Plugin stdio bridge", () => {
  const services: TestBridge[] = [];

  afterEach(async () => {
    await Promise.all(services.splice(0).map((service) => service.stop()));
  });

  function createBridge() {
    const processTracking = {
      register: vi.fn(),
      unregister: vi.fn(),
      kill: vi.fn(),
    } as unknown as ProcessTrackingService;
    const service = new TestBridge(processTracking, rootLogger);
    services.push(service);
    return { service, processTracking };
  }

  it("relays MCP over HTTP and tracks the managed child process", async () => {
    const { service, processTracking } = createBridge();
    const url = await service.register(registration("server"));

    const response = await initialize(url);

    expect(response.status).toBe(200);
    expect(await response.text()).toContain('"id":1');
    expect(processTracking.register).toHaveBeenCalledWith(
      1000,
      "child",
      "agent-plugin:server",
      expect.objectContaining({ taskRunId: "run-1" }),
      "run-1",
    );

    await service.unregisterRun("run-1");
    expect(processTracking.kill).toHaveBeenCalledWith(1000);
  });

  it("uses a disposable process for the Codex reachability probe", async () => {
    const { service, processTracking } = createBridge();
    const url = await service.register(registration("server"));

    expect((await initialize(url, true)).status).toBe(200);
    expect((await initialize(url)).status).toBe(200);

    expect(service.transports).toHaveLength(2);
    expect(service.transports[0].close).toHaveBeenCalledOnce();
    expect(service.transports[1].close).not.toHaveBeenCalled();
    expect(processTracking.kill).toHaveBeenCalledWith(1000);
  });

  it("isolates one spawn failure from a sibling stdio server", async () => {
    const { service } = createBridge();
    const failed = registration("failed", {
      command: "fail",
      onFailure: vi.fn(),
    });
    const healthy = registration("healthy", { runId: "run-2" });
    const failedUrl = await service.register(failed);
    const healthyUrl = await service.register(healthy);

    const failedResponse = await initialize(failedUrl);
    const healthyResponse = await initialize(healthyUrl);

    expect(failedResponse.status).toBe(502);
    expect(failed.onFailure).toHaveBeenCalledOnce();
    expect(healthyResponse.status).toBe(200);
  });

  it("reports an unexpected stdio crash without stopping a sibling", async () => {
    const { service, processTracking } = createBridge();
    const crashed = registration("crashed", { onFailure: vi.fn() });
    const sibling = registration("sibling", { runId: "run-2" });
    const crashedUrl = await service.register(crashed);
    const siblingUrl = await service.register(sibling);
    await initialize(crashedUrl);
    await initialize(siblingUrl);

    service.transports[0].onclose?.();

    expect(crashed.onFailure).toHaveBeenCalledOnce();
    await service.unregisterRun("run-2");
    expect(processTracking.kill).toHaveBeenCalledWith(1001);
  });

  it("stops every process for a disabled installation", async () => {
    const { service, processTracking } = createBridge();
    const firstUrl = await service.register(registration("first"));
    const secondUrl = await service.register(
      registration("second", { runId: "run-2" }),
    );
    await initialize(firstUrl);
    await initialize(secondUrl);

    await service.unregisterInstallation("installation-1");

    expect(processTracking.kill).toHaveBeenCalledWith(1000);
    expect(processTracking.kill).toHaveBeenCalledWith(1001);
  });
});
