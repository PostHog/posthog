import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const check = vi.fn();
  const create = vi.fn();
  const createCommand = vi.fn();
  const write = vi.fn();
  const resize = vi.fn();
  const openExternal = vi.fn();
  const logInfo = vi.fn();
  const logError = vi.fn();
  const logWarn = vi.fn();

  class MockTerminal {
    cols = 80;
    rows = 24;
    options: Record<string, unknown>;
    dataHandler: ((data: string) => void) | null = null;
    loadAddon = vi.fn();
    attachCustomKeyEventHandler = vi.fn();
    write = vi.fn();
    writeln = vi.fn();
    clear = vi.fn();
    refresh = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();

    constructor(options: Record<string, unknown>) {
      this.options = options;
      terminalInstances.push(this);
    }

    onData(handler: (data: string) => void) {
      this.dataHandler = handler;
      return { dispose: vi.fn() };
    }

    open(element: HTMLElement) {
      const terminalElement = document.createElement("div");
      terminalElement.className = "xterm";
      element.appendChild(terminalElement);
    }

    emitData(data: string) {
      this.dataHandler?.(data);
    }
  }

  const terminalInstances: MockTerminal[] = [];

  return {
    check,
    create,
    createCommand,
    write,
    resize,
    openExternal,
    logInfo,
    logError,
    logWarn,
    MockTerminal,
    terminalInstances,
  };
});

vi.mock("@posthog/di/container", () => ({
  resolveService: () => ({
    check: mocks.check,
    create: mocks.create,
    createCommand: mocks.createCommand,
    write: mocks.write,
    resize: mocks.resize,
    openExternal: mocks.openExternal,
  }),
}));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      info: mocks.logInfo,
      error: mocks.logError,
      warn: mocks.logWarn,
    }),
  },
}));

vi.mock("@posthog/ui/utils/platform", () => ({
  isMac: false,
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));

vi.mock("@xterm/addon-serialize", () => ({
  SerializeAddon: class {
    serialize = vi.fn(() => "serialized-terminal-state");
  },
}));

vi.mock("@xterm/addon-web-links", () => ({
  WebLinksAddon: class {},
}));

vi.mock("@xterm/addon-webgl", () => ({
  WebglAddon: class {
    onContextLoss = vi.fn();
    dispose = vi.fn();
  },
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: mocks.MockTerminal,
}));

import { terminalManager } from "./TerminalManager";

describe("TerminalManager shell recovery", () => {
  const sessionId = "shell-recovery-test";

  beforeEach(() => {
    mocks.check.mockReset();
    mocks.create.mockReset();
    mocks.createCommand.mockReset();
    mocks.write.mockReset();
    mocks.resize.mockReset();
    mocks.openExternal.mockReset();
    mocks.logInfo.mockReset();
    mocks.logError.mockReset();
    mocks.terminalInstances.length = 0;

    mocks.check.mockResolvedValue(true);
    mocks.create.mockResolvedValue(undefined);
    mocks.createCommand.mockResolvedValue(undefined);
    mocks.write.mockResolvedValue(undefined);
    mocks.resize.mockResolvedValue(undefined);
  });

  afterEach(() => {
    terminalManager.destroy(sessionId);
  });

  it("recreates a missing interactive shell and retries the triggering input", async () => {
    terminalManager.create({
      sessionId,
      persistenceKey: "task-1-shell",
      cwd: "/repo",
      taskId: "task-1",
    });

    await vi.waitFor(() => {
      expect(mocks.check).toHaveBeenCalledWith({ sessionId });
    });

    mocks.check.mockResolvedValueOnce(false);
    mocks.write
      .mockRejectedValueOnce(new Error(`Shell session ${sessionId} not found`))
      .mockResolvedValue(undefined);

    mocks.terminalInstances[0].emitData("a");

    await vi.waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith({
        sessionId,
        cwd: "/repo",
        taskId: "task-1",
      });
    });

    await vi.waitFor(() => {
      expect(mocks.write).toHaveBeenCalledTimes(2);
    });

    expect(mocks.write.mock.calls[1][0]).toEqual({
      sessionId,
      data: "a",
    });
  });
});

describe("TerminalManager.destroyForTask", () => {
  beforeEach(() => {
    mocks.check.mockReset().mockResolvedValue(true);
    mocks.create.mockReset().mockResolvedValue(undefined);
    mocks.write.mockReset().mockResolvedValue(undefined);
    mocks.resize.mockReset().mockResolvedValue(undefined);
    mocks.terminalInstances.length = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    for (const id of terminalManager.getSessionsByPrefix("")) {
      terminalManager.destroy(id);
    }
    vi.unstubAllGlobals();
  });

  it("destroys the task's main and action terminals only", () => {
    terminalManager.create({
      sessionId: "sess-a",
      persistenceKey: "task-1",
      taskId: "task-1",
    });
    terminalManager.create({
      sessionId: "sess-b",
      // Production action-terminal key shape: the taskId sits mid-key, so
      // only the tagged instance.taskId can match it.
      persistenceKey: "action-setup-task-1-1700000000000-0",
      taskId: "task-1",
    });
    terminalManager.create({
      sessionId: "sess-c",
      persistenceKey: "task-10",
      taskId: "task-10",
    });

    terminalManager.destroyForTask("task-1");

    expect(terminalManager.getSessionsByPrefix("sess-")).toEqual(["sess-c"]);
    expect(mocks.terminalInstances[0].dispose).toHaveBeenCalled();
    expect(mocks.terminalInstances[1].dispose).toHaveBeenCalled();
    expect(mocks.terminalInstances[2].dispose).not.toHaveBeenCalled();
  });

  it("falls back to the persistence key when an instance has no taskId", () => {
    terminalManager.create({
      sessionId: "sess-d",
      persistenceKey: "task-3-shell",
    });
    terminalManager.create({
      sessionId: "sess-e",
      persistenceKey: "task-30-shell",
    });

    terminalManager.destroyForTask("task-3");

    expect(terminalManager.getSessionsByPrefix("sess-")).toEqual(["sess-e"]);
  });

  it("removes the parked terminal element from the DOM on destroy", () => {
    terminalManager.create({
      sessionId: "sess-parked",
      persistenceKey: "task-2",
      taskId: "task-2",
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    terminalManager.attach("sess-parked", host);
    terminalManager.detach("sess-parked");

    const parking = document.getElementById("terminal-parking");
    expect(parking?.classList.contains("ph-no-capture")).toBe(true);
    expect(parking?.childElementCount).toBe(1);

    terminalManager.destroy("sess-parked");
    expect(parking?.childElementCount).toBe(0);
    host.remove();
  });
});

describe("TerminalManager custom key handling", () => {
  const sessionId = "key-handler-test";

  beforeEach(() => {
    mocks.check.mockReset().mockResolvedValue(true);
    mocks.create.mockReset().mockResolvedValue(undefined);
    mocks.write.mockReset().mockResolvedValue(undefined);
    mocks.resize.mockReset().mockResolvedValue(undefined);
    mocks.terminalInstances.length = 0;
  });

  afterEach(() => {
    terminalManager.destroy(sessionId);
  });

  function keyHandler() {
    terminalManager.create({ sessionId, persistenceKey: "task-key" });
    const instance = mocks.terminalInstances[0];
    return instance.attachCustomKeyEventHandler.mock.calls[0][0] as (
      event: KeyboardEvent,
    ) => boolean;
  }

  function fakeEvent(overrides: Partial<KeyboardEvent>): KeyboardEvent {
    return {
      key: "k",
      type: "keydown",
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      stopImmediatePropagation: vi.fn(),
      ...overrides,
    } as unknown as KeyboardEvent;
  }

  it("clears the terminal and stops ctrl+k from bubbling to the command menu", () => {
    const handler = keyHandler();
    const event = fakeEvent({ key: "k", ctrlKey: true, type: "keydown" });

    const result = handler(event);

    expect(result).toBe(false);
    expect(mocks.terminalInstances[0].clear).toHaveBeenCalledTimes(1);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(event.stopPropagation).toHaveBeenCalledTimes(1);
    expect(event.stopImmediatePropagation).toHaveBeenCalledTimes(1);
  });

  it("lets ctrl+w keep bubbling so global handlers can act", () => {
    const handler = keyHandler();
    const event = fakeEvent({ key: "w", ctrlKey: true });

    const result = handler(event);

    expect(result).toBe(false);
    expect(event.stopPropagation).not.toHaveBeenCalled();
    expect(event.stopImmediatePropagation).not.toHaveBeenCalled();
  });
});
