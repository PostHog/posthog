import type { ISketchpadService } from "@posthog/core/sketchpad/identifiers";
import {
  estimateJsonBytes,
  type HostToSketchpadFrameMessage,
  isField,
  isReservedStateKey,
  isSafePostHogUrl,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_STATE_KEY_MAX_CHARS,
  type SketchpadDataMethod,
  type SketchpadFrameToHostMessage,
} from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import {
  SKETCHPAD_REQUEST_TOO_LARGE,
  SKETCHPAD_TOO_MANY_READS_AT_ONCE,
} from "../sketchpadCopy";
import {
  handleSketchpadDataRequest,
  type SketchpadBudget,
  type SketchpadDataBridgeContext,
} from "./sketchpadDataBridge";
import type { UseSketchpadFrameOptions } from "./useSketchpadFrame";

const log = logger.scope("sketchpad-frame");
const MAX_PENDING_DATA_REQUESTS = 200;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const MAX_TEXT_EDIT_REQUEST_BYTES = 2 * 1024 * 1024;
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1000;

function requestByteLimit(method: SketchpadDataMethod): number {
  return method === "stateEditText"
    ? MAX_TEXT_EDIT_REQUEST_BYTES
    : MAX_DATA_REQUEST_BYTES;
}

interface SketchpadHostMessageRouterOptions {
  post: (message: HostToSketchpadFrameMessage) => void;
  signal: AbortSignal;
  callbacks: () => UseSketchpadFrameOptions;
  budget: SketchpadBudget;
  compiled: ISketchpadService["compiled"];
  hasUserActivation: () => boolean;
  openExternal: (url: string) => void;
  onReady: () => void;
  onStateEcho: (key: string, value: unknown) => void;
}

export function createSketchpadHostMessageRouter(
  options: SketchpadHostMessageRouterOptions,
): (message: SketchpadFrameToHostMessage) => void {
  let activeRequests = 0;
  let lastExternalOpen = 0;

  const reply = (
    id: string,
    ok: boolean,
    result?: unknown,
    error?: string,
  ): void => {
    if (options.signal.aborted) return;
    options.post({
      channel: SKETCHPAD_CHANNEL,
      type: "data-response",
      id,
      ok,
      result,
      error,
    });
  };

  const runDataRequest = async (
    message: Extract<SketchpadFrameToHostMessage, { type: "data-request" }>,
  ): Promise<void> => {
    if (activeRequests >= MAX_PENDING_DATA_REQUESTS) {
      reply(message.id, false, undefined, SKETCHPAD_TOO_MANY_READS_AT_ONCE);
      return;
    }
    if (estimateJsonBytes(message.payload) > requestByteLimit(message.method)) {
      reply(message.id, false, undefined, SKETCHPAD_REQUEST_TOO_LARGE);
      return;
    }
    activeRequests += 1;
    const { sketchpadId, queryClient, getSnapshot, applyLocal, reportCaret } =
      options.callbacks();
    const ctx: SketchpadDataBridgeContext = {
      sketchpadId,
      queryClient,
      getSnapshot,
      applyLocal,
      reportCaret,
      signal: options.signal,
      budget: options.budget,
    };
    try {
      const result = await handleSketchpadDataRequest(
        message.method,
        message.payload,
        ctx,
      );
      reply(message.id, true, result);
    } catch (error) {
      reply(
        message.id,
        false,
        undefined,
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      activeRequests -= 1;
    }
  };

  let compiling = false;
  const runCompileRequest = async (
    message: Extract<SketchpadFrameToHostMessage, { type: "compile-request" }>,
  ): Promise<void> => {
    if (compiling) {
      reply(
        message.id,
        false,
        undefined,
        "A fragment compilation request is already active.",
      );
      return;
    }
    compiling = true;
    try {
      reply(
        message.id,
        true,
        await options.compiled(
          options.budget.sketchpadId,
          message.refs,
          options.signal,
        ),
      );
    } catch (error) {
      reply(
        message.id,
        false,
        undefined,
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      compiling = false;
    }
  };

  const route = (message: SketchpadFrameToHostMessage): void => {
    const events = options.callbacks().events;
    switch (message.type) {
      case "compile-request":
        void runCompileRequest(message);
        break;
      case "ready":
        options.onReady();
        events.onReady();
        break;
      case "exit-focus":
        events.onExitFocus();
        break;
      case "fragment-rendered":
        events.onFragmentRendered(message.id);
        break;
      case "fragment-error":
        events.onFragmentError(message.id, message.message, message.stack);
        break;
      case "state-changed":
        if (
          isReservedStateKey(message.key) ||
          message.key.length > SKETCHPAD_STATE_KEY_MAX_CHARS
        ) {
          log.warn("Refused a fragment state key");
          break;
        }
        if (isField(options.callbacks().getSnapshot().state[message.key]))
          break;
        if (!options.budget.writes.take(Date.now())) {
          log.warn("Paused a fragment that writes shared state too fast");
          break;
        }
        options.onStateEcho(message.key, message.value ?? null);
        events.onStateChanged(message.key, message.value);
        break;
      case "policy-violation":
        log.warn("A fragment tried a channel the board closes", {
          directive: message.directive,
          blocked: message.blocked,
        });
        break;
      case "data-request":
        void runDataRequest(message);
        break;
      case "wheel":
        events.onWheel(message);
        break;
      case "background-pointer":
        events.onBackgroundPointer(message);
        break;
      case "fragment-pointer-down":
        events.onFragmentPointerDown(message);
        break;
      case "pointer-move":
        events.onPointerMove(message.clientX, message.clientY);
        break;
      case "pointer-leave":
        events.onPointerLeave();
        break;
      case "open-external": {
        const now = Date.now();
        if (!isSafePostHogUrl(message.url)) {
          log.warn("Blocked non-PostHog fragment external URL");
        } else if (!options.hasUserActivation()) {
          log.warn("Ignored fragment external URL open without interaction");
        } else if (now - lastExternalOpen < EXTERNAL_OPEN_MIN_INTERVAL_MS) {
          log.warn("Throttled fragment external URL open");
        } else {
          lastExternalOpen = now;
          options.openExternal(message.url);
        }
        break;
      }
    }
  };

  return route;
}
