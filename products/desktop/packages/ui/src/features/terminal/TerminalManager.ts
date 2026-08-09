import { DEFAULT_TERMINAL_FONT_FAMILY } from "@posthog/core/terminal/resolveTerminalFontFamily";
import { resolveService } from "@posthog/di/container";
import { getErrorMessage } from "@posthog/shared";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { logger } from "@posthog/ui/shell/logger";
import { isMac } from "@posthog/ui/utils/platform";
import { FitAddon } from "@xterm/addon-fit";
import { SerializeAddon } from "@xterm/addon-serialize";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { WebglAddon } from "@xterm/addon-webgl";
import { Terminal as XTerm } from "@xterm/xterm";

const log = logger.scope("terminal-manager");

let parkingContainer: HTMLElement | null = null;

function getParkingContainer(): HTMLElement {
  if (!parkingContainer) {
    parkingContainer = document.createElement("div");
    parkingContainer.id = "terminal-parking";
    // Parked terminals keep live WebGL canvases; ph-no-capture stops PostHog
    // session replay snapshotting every one of them at canvasFps forever.
    parkingContainer.className = "ph-no-capture";
    parkingContainer.style.position = "absolute";
    parkingContainer.style.visibility = "hidden";
    parkingContainer.style.pointerEvents = "none";
    parkingContainer.style.width = "0";
    parkingContainer.style.height = "0";
    parkingContainer.style.overflow = "hidden";
    document.body.appendChild(parkingContainer);
  }
  return parkingContainer;
}

export interface TerminalInstance {
  term: XTerm;
  fitAddon: FitAddon;
  serializeAddon: SerializeAddon;
  webglAddon: WebglAddon | null;
  writeBuffer: string;
  flushHandle: number | null;
  attachedElement: HTMLElement | null;
  terminalElement: HTMLElement | null;
  isReady: boolean;
  hasOpened: boolean;
  cleanups: Array<() => void>;
  resizeObserver: ResizeObserver | null;
  saveTimeout: number | null;
  persistenceKey: string;
  cwd?: string;
  taskId?: string;
  command?: string;
  recoveryPromise: Promise<void> | null;
}

export interface CreateOptions {
  sessionId: string;
  persistenceKey: string;
  cwd?: string;
  initialState?: string;
  taskId?: string;
  command?: string;
}

type ReadyPayload = { sessionId: string; persistenceKey: string };
type ExitPayload = {
  sessionId: string;
  persistenceKey: string;
  exitCode?: number;
};
type StateChangePayload = {
  sessionId: string;
  persistenceKey: string;
  serializedState: string;
};

type EventPayloadMap = {
  ready: ReadyPayload;
  exit: ExitPayload;
  stateChange: StateChangePayload;
};

type EventType = keyof EventPayloadMap;
type Listener<T extends EventType> = (payload: EventPayloadMap[T]) => void;

function getTerminalTheme(isDarkMode: boolean) {
  return isDarkMode
    ? {
        background: "#131316",
        foreground: "#e6e6e6",
        cursor: "#f8be2a",
        cursorAccent: "#131316",
        selectionBackground: "rgba(248, 190, 42, 0.25)",
        selectionInactiveBackground: "rgba(248, 190, 42, 0.12)",
        selectionForeground: "#e6e6e6",
      }
    : {
        background: "#f2f3ee",
        foreground: "#3a4036",
        cursor: "#f54d00",
        cursorAccent: "#f2f3ee",
        selectionBackground: "#fbd0b8",
        selectionInactiveBackground: "#f3e2d6",
        selectionForeground: "#3a4036",
      };
}

function loadAddons(term: XTerm) {
  const fit = new FitAddon();
  const serialize = new SerializeAddon();

  const activateLink = (_event: MouseEvent, uri: string) => {
    resolveService<ShellClient>(SHELL_CLIENT)
      .openExternal({ url: uri })
      .catch((error: Error) => {
        log.error("Failed to open link:", uri, error);
      });
  };

  const webLinks = new WebLinksAddon(activateLink);

  term.loadAddon(fit);
  term.loadAddon(serialize);
  term.loadAddon(webLinks);

  return { fit, serialize };
}

function attachKeyHandlers(term: XTerm) {
  term.attachCustomKeyEventHandler((event: KeyboardEvent) => {
    const cmdOrCtrl = isMac ? event.metaKey : event.ctrlKey;

    if (event.key === "k" && cmdOrCtrl && event.type === "keydown") {
      event.preventDefault();
      // Stop the keydown from bubbling to the document-level mod+k hotkey,
      // which would otherwise open the command menu on every terminal clear.
      event.stopPropagation();
      event.stopImmediatePropagation();
      term.clear();
      return false;
    }

    if (event.key === "w" && cmdOrCtrl) {
      return false;
    }

    if (event.key === "r" && cmdOrCtrl && !event.shiftKey) {
      return false;
    }

    if (cmdOrCtrl && event.key >= "1" && event.key <= "9") {
      return false;
    }

    return true;
  });
}

function isMissingShellSessionError(
  error: unknown,
  sessionId: string,
): boolean {
  return getErrorMessage(error).includes(
    `Shell session ${sessionId} not found`,
  );
}

class TerminalManagerImpl {
  private instances = new Map<string, TerminalInstance>();
  private listeners = new Map<EventType, Set<Listener<EventType>>>();
  private isDarkMode = true;
  private fontFamily: string = DEFAULT_TERMINAL_FONT_FAMILY;
  private useWebgl = true;

  has(sessionId: string): boolean {
    return this.instances.has(sessionId);
  }

  get(sessionId: string): TerminalInstance | undefined {
    return this.instances.get(sessionId);
  }

  create(options: CreateOptions): TerminalInstance {
    const { sessionId, persistenceKey, cwd, initialState, taskId, command } =
      options;

    const existing = this.instances.get(sessionId);
    if (existing) {
      return existing;
    }

    const term = new XTerm({
      cursorBlink: true,
      fontSize: 12,
      fontFamily: this.fontFamily,
      theme: getTerminalTheme(this.isDarkMode),
      cursorStyle: "block",
      cursorWidth: 8,
      allowProposedApi: true,
    });

    const { fit, serialize } = loadAddons(term);
    attachKeyHandlers(term);

    const instance: TerminalInstance = {
      term,
      fitAddon: fit,
      serializeAddon: serialize,
      webglAddon: null,
      writeBuffer: "",
      flushHandle: null,
      attachedElement: null,
      terminalElement: null,
      isReady: false,
      hasOpened: false,
      cleanups: [],
      resizeObserver: null,
      saveTimeout: null,
      persistenceKey,
      cwd,
      taskId,
      command,
      recoveryPromise: null,
    };

    if (initialState) {
      term.write(initialState);
    }

    // Setup user input handler
    const disposable = term.onData((data: string) => {
      resolveService<ShellClient>(SHELL_CLIENT)
        .write({ sessionId, data })
        .catch((error: Error) => {
          this.handleMissingSessionError(sessionId, instance, error, {
            reason: "write",
            retryData: data,
          });
        });
      this.scheduleSave(sessionId, instance);
    });
    instance.cleanups.push(() => disposable.dispose());

    // Initialize shell session
    this.initializeSession(sessionId, instance, cwd, taskId, command);

    this.instances.set(sessionId, instance);
    return instance;
  }

  private async initializeSession(
    sessionId: string,
    instance: TerminalInstance,
    cwd?: string,
    taskId?: string,
    command?: string,
  ): Promise<void> {
    try {
      const sessionExists = await resolveService<ShellClient>(
        SHELL_CLIENT,
      ).check({ sessionId });
      if (!sessionExists) {
        if (instance.attachedElement) {
          instance.fitAddon.fit();
        }

        if (command && cwd) {
          await resolveService<ShellClient>(SHELL_CLIENT).createCommand({
            sessionId,
            command,
            cwd,
            taskId,
          });
        } else {
          await resolveService<ShellClient>(SHELL_CLIENT).create({
            sessionId,
            cwd,
            taskId,
          });
        }
      }

      instance.isReady = true;

      if (instance.attachedElement) {
        instance.fitAddon.fit();
        resolveService<ShellClient>(SHELL_CLIENT)
          .resize({
            sessionId,
            cols: instance.term.cols,
            rows: instance.term.rows,
          })
          .catch((error: Error) => {
            log.error("Failed to sync initial terminal size:", error);
          });
      }

      this.emit("ready", {
        sessionId,
        persistenceKey: instance.persistenceKey,
      });
    } catch (error) {
      log.error("Failed to initialize session:", sessionId, error);
      instance.term.writeln(
        `\r\n\x1b[31mFailed to create shell: ${(error as Error).message}\x1b[0m\r\n`,
      );
    }
  }

  writeData(sessionId: string, data: string): void {
    const instance = this.instances.get(sessionId);
    if (!instance) {
      return;
    }

    // Coalesce bursts of pty output into a single term.write() per animation
    // frame instead of one call per IPC chunk, cutting the per-call parse and
    // write-buffer overhead that piles up on the main thread under a heavy
    // stream (build logs, cat-ing a file).
    instance.writeBuffer += data;
    if (instance.flushHandle === null) {
      instance.flushHandle = requestAnimationFrame(() => {
        instance.flushHandle = null;
        this.flushWrite(sessionId, instance);
      });
    }
  }

  private flushWrite(sessionId: string, instance: TerminalInstance): void {
    if (instance.flushHandle !== null) {
      cancelAnimationFrame(instance.flushHandle);
      instance.flushHandle = null;
    }
    if (instance.writeBuffer.length === 0) {
      return;
    }
    const data = instance.writeBuffer;
    instance.writeBuffer = "";
    instance.term.write(data);
    this.scheduleSave(sessionId, instance);
  }

  handleExit(sessionId: string, exitCode?: number): void {
    const instance = this.instances.get(sessionId);
    if (instance) {
      // Without this, ResizeObserver keeps firing shell.resize against the dead
      // session on every layout shift, producing a TRPC error per call and
      // wedging the renderer.
      instance.isReady = false;
      this.disconnectResizeObserver(instance);
      this.emit("exit", {
        sessionId,
        persistenceKey: instance.persistenceKey,
        exitCode,
      });
    }
  }

  private disconnectResizeObserver(instance: TerminalInstance): void {
    if (instance.resizeObserver) {
      instance.resizeObserver.disconnect();
      instance.resizeObserver = null;
    }
  }

  private handleMissingSessionError(
    sessionId: string,
    instance: TerminalInstance,
    error: unknown,
    options: { reason: "write" | "resize"; retryData?: string },
  ): void {
    if (!isMissingShellSessionError(error, sessionId)) {
      log.error(`Failed to ${options.reason} shell:`, error);
      return;
    }

    this.recoverMissingSession(sessionId, instance, options.reason)
      .then(() => {
        if (options.retryData === undefined || !instance.isReady) {
          return;
        }

        return resolveService<ShellClient>(SHELL_CLIENT)
          .write({ sessionId, data: options.retryData })
          .catch((retryError: Error) => {
            log.error(
              "Failed to retry write after shell recovery:",
              retryError,
            );
          });
      })
      .catch((recoveryError: Error) => {
        log.error("Failed to recover missing shell session:", recoveryError);
      });
  }

  private recoverMissingSession(
    sessionId: string,
    instance: TerminalInstance,
    reason: "write" | "resize",
  ): Promise<void> {
    if (instance.command) {
      this.handleExit(sessionId);
      return Promise.resolve();
    }

    if (instance.recoveryPromise) {
      return instance.recoveryPromise;
    }

    log.info("Recovering missing shell session", { sessionId, reason });
    instance.isReady = false;

    instance.recoveryPromise = this.initializeSession(
      sessionId,
      instance,
      instance.cwd,
      instance.taskId,
    ).finally(() => {
      instance.recoveryPromise = null;
    });

    return instance.recoveryPromise;
  }

  private scheduleSave(sessionId: string, instance: TerminalInstance): void {
    if (instance.saveTimeout) {
      clearTimeout(instance.saveTimeout);
    }

    instance.saveTimeout = window.setTimeout(() => {
      const serialized = instance.serializeAddon.serialize();
      this.emit("stateChange", {
        sessionId,
        persistenceKey: instance.persistenceKey,
        serializedState: serialized,
      });
    }, 500);
  }

  // The WebGL renderer must be loaded after term.open() — it needs the canvas
  // the terminal creates on attach. Without it xterm falls back to its DOM
  // renderer, which is slower under heavy output.
  private loadWebglRenderer(instance: TerminalInstance): void {
    if (!this.useWebgl || instance.webglAddon) {
      return;
    }
    try {
      const webglAddon = new WebglAddon();
      webglAddon.onContextLoss(() => {
        // GPU context lost (e.g. driver reset). Drop the addon so xterm falls
        // back to the DOM renderer rather than rendering nothing.
        webglAddon.dispose();
        instance.webglAddon = null;
      });
      instance.term.loadAddon(webglAddon);
      instance.webglAddon = webglAddon;
    } catch (error) {
      log.warn(
        "WebGL renderer unavailable, using DOM renderer instead:",
        error,
      );
    }
  }

  attach(sessionId: string, element: HTMLElement): void {
    const instance = this.instances.get(sessionId);
    if (!instance) {
      log.error("Cannot attach: instance not found:", sessionId);
      return;
    }

    if (instance.attachedElement === element) {
      return;
    }

    this.disconnectResizeObserver(instance);

    instance.attachedElement = element;

    if (!instance.hasOpened) {
      instance.term.open(element);
      instance.hasOpened = true;
      instance.terminalElement = element.querySelector(".xterm") as HTMLElement;
      this.loadWebglRenderer(instance);
    } else if (instance.terminalElement) {
      element.appendChild(instance.terminalElement);
      // Detach dropped the WebGL renderer to free its GPU context; restore it
      // now that the terminal is visible again.
      this.loadWebglRenderer(instance);
      instance.term.refresh(0, instance.term.rows - 1);
    }

    const handleResize = () => {
      if (instance.fitAddon) {
        instance.fitAddon.fit();

        if (instance.isReady) {
          resolveService<ShellClient>(SHELL_CLIENT)
            .resize({
              sessionId,
              cols: instance.term.cols,
              rows: instance.term.rows,
            })
            .catch((error: Error) => {
              this.handleMissingSessionError(sessionId, instance, error, {
                reason: "resize",
              });
            });
        }
      }
    };

    instance.resizeObserver = new ResizeObserver(handleResize);
    instance.resizeObserver.observe(element);

    setTimeout(() => {
      instance.fitAddon.fit();
    }, 0);
  }

  detach(sessionId: string): void {
    const instance = this.instances.get(sessionId);
    if (!instance || !instance.attachedElement) {
      return;
    }

    this.disconnectResizeObserver(instance);

    // Drain buffered output so the serialized snapshot reflects the latest data.
    this.flushWrite(sessionId, instance);

    const serialized = instance.serializeAddon.serialize();
    this.emit("stateChange", {
      sessionId,
      persistenceKey: instance.persistenceKey,
      serializedState: serialized,
    });

    if (instance.terminalElement) {
      getParkingContainer().appendChild(instance.terminalElement);
    }

    // A parked terminal renders nothing, but a live WebglAddon still holds a
    // GPU context (Chromium also drops the oldest context past 16). Release
    // it; attach() reloads it when the terminal becomes visible again.
    if (instance.webglAddon) {
      instance.webglAddon.dispose();
      instance.webglAddon = null;
    }

    instance.attachedElement = null;
  }

  destroy(sessionId: string): void {
    const instance = this.instances.get(sessionId);
    if (!instance) {
      return;
    }

    if (instance.attachedElement) {
      this.detach(sessionId);
    }

    if (instance.saveTimeout) {
      clearTimeout(instance.saveTimeout);
    }

    if (instance.flushHandle !== null) {
      cancelAnimationFrame(instance.flushHandle);
      instance.flushHandle = null;
    }

    instance.webglAddon?.dispose();
    instance.webglAddon = null;

    for (const cleanup of instance.cleanups) {
      cleanup();
    }

    instance.term.dispose();

    instance.terminalElement?.remove();
    instance.terminalElement = null;

    this.instances.delete(sessionId);
  }

  destroyForTask(taskId: string): void {
    for (const [sessionId, instance] of this.instances) {
      // Action terminals embed the taskId mid-key (`action-setup-<taskId>-…`),
      // so the tagged taskId is authoritative; the key match covers instances
      // created without one.
      const key = instance.persistenceKey;
      if (
        instance.taskId === taskId ||
        key === taskId ||
        key.startsWith(`${taskId}-`)
      ) {
        this.destroy(sessionId);
      }
    }
  }

  focus(sessionId: string): void {
    const instance = this.instances.get(sessionId);
    if (instance) {
      instance.term.focus();
    }
  }

  clear(sessionId: string): void {
    const instance = this.instances.get(sessionId);
    if (instance) {
      instance.term.clear();
    }
  }

  serialize(sessionId: string): string | null {
    const instance = this.instances.get(sessionId);
    if (!instance) {
      return null;
    }
    return instance.serializeAddon.serialize();
  }

  setTheme(isDarkMode: boolean): void {
    if (this.isDarkMode === isDarkMode) {
      return;
    }

    this.isDarkMode = isDarkMode;
    const theme = getTerminalTheme(isDarkMode);

    for (const instance of this.instances.values()) {
      instance.term.options.theme = theme;
    }
  }

  setFontFamily(fontFamily: string): void {
    if (this.fontFamily === fontFamily) {
      return;
    }

    this.fontFamily = fontFamily;

    for (const instance of this.instances.values()) {
      instance.term.options.fontFamily = fontFamily;
      // Parked terminals live in a 0x0 container, so fit would compute garbage.
      // attach() refits on reattachment, so skipping here is safe.
      if (!instance.attachedElement) continue;
      try {
        instance.fitAddon.fit();
      } catch (error) {
        log.error("Failed to refit after font change:", error);
      }
    }
  }

  setUseWebgl(enabled: boolean): void {
    if (this.useWebgl === enabled) {
      return;
    }

    this.useWebgl = enabled;

    for (const instance of this.instances.values()) {
      if (enabled) {
        // Only opened terminals have the canvas WebGL needs; the rest pick it
        // up the first time they attach.
        if (instance.hasOpened) {
          this.loadWebglRenderer(instance);
        }
      } else if (instance.webglAddon) {
        // Disposing the addon makes xterm fall back to its DOM renderer.
        instance.webglAddon.dispose();
        instance.webglAddon = null;
      }
    }
  }

  on<T extends EventType>(event: T, listener: Listener<T>): () => void {
    let listeners = this.listeners.get(event);
    if (!listeners) {
      listeners = new Set();
      this.listeners.set(event, listeners);
    }

    listeners.add(listener as Listener<EventType>);

    return () => {
      listeners.delete(listener as Listener<EventType>);
    };
  }

  private emit<T extends EventType>(
    event: T,
    payload: EventPayloadMap[T],
  ): void {
    const listeners = this.listeners.get(event);
    if (listeners) {
      for (const listener of listeners) {
        try {
          listener(payload);
        } catch (error) {
          log.error("Event listener error:", event, error);
        }
      }
    }
  }

  getSessionsByPrefix(prefix: string): string[] {
    const result: string[] = [];
    for (const sessionId of this.instances.keys()) {
      if (sessionId.startsWith(prefix)) {
        result.push(sessionId);
      }
    }
    return result;
  }
}

export const terminalManager = new TerminalManagerImpl();
