<<<<<<< HEAD
import { buildSketchpadFrameDocument } from "@posthog/core/sketchpad/frameDocument";
import {
  fragmentsEqual,
  type HostToSketchpadFrameMessage,
  SKETCHPAD_CHANNEL,
=======
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  estimateJsonBytes,
  fragmentsEqual,
  type HostToSketchpadFrameMessage,
  isField,
  isReservedStateKey,
  isSafePostHogUrl,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_STATE_KEY_MAX_CHARS,
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  type SketchpadFrameCaret,
  type SketchpadFrameToHostMessage,
  type SketchpadOp,
  type SketchpadPresenceCaret,
  type SketchpadSnapshot,
  type SketchpadTheme,
  type SketchpadViewport,
  sketchpadFrameToHostMessageSchema,
} from "@posthog/shared";
import { useSketchpadApi } from "@posthog/ui/features/sketchpad/hooks/useSketchpadApi";
<<<<<<< HEAD
import { fieldMessageValue } from "@posthog/ui/features/sketchpad/runtime/sketchpadFieldMessages";
=======
import { spendSketchpadWrite } from "@posthog/ui/features/sketchpad/runtime/sketchpadDataBridge";
import { fieldMessageValue } from "@posthog/ui/features/sketchpad/runtime/sketchpadFieldMessages";
import { SKETCHPAD_TOO_MANY_READS_AT_ONCE } from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { logger } from "@posthog/ui/shell/logger";
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import type { QueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
<<<<<<< HEAD
import { createSketchpadBudget } from "./sketchpadDataBridge";
=======
import {
  handleSketchpadDataRequest,
  type SketchpadDataBridgeContext,
} from "./sketchpadDataBridge";
import {
  buildSketchpadFrameDocument,
  sketchpadFramePolicy,
} from "./sketchpadFrameDocument";
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
import {
  listenToSketchpadFrame,
  type SketchpadFrameElement,
  sendToSketchpadFrame,
} from "./sketchpadFrameElement";
<<<<<<< HEAD
import { createSketchpadHostMessageRouter } from "./sketchpadHostMessageRouter";
=======

const log = logger.scope("sketchpad-frame");

const MAX_PENDING_DATA_REQUESTS = 200;
const MAX_DATA_REQUEST_BYTES = 64 * 1024;
const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000;
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)

export interface SketchpadFrameEvents {
  onExitFocus(): void;
  onReady(): void;
  onFragmentRendered(id: string): void;
  onFragmentError(id: string, message: string, stack?: string): void;
  onStateChanged(key: string, value: unknown): void;
  onWheel(e: Extract<SketchpadFrameToHostMessage, { type: "wheel" }>): void;
  onBackgroundPointer(
    e: Extract<SketchpadFrameToHostMessage, { type: "background-pointer" }>,
  ): void;
  onFragmentPointerDown(
    e: Extract<SketchpadFrameToHostMessage, { type: "fragment-pointer-down" }>,
  ): void;
  onPointerMove(clientX: number, clientY: number): void;
  onPointerLeave(): void;
}

export interface UseSketchpadFrameOptions {
  sketchpadId: string;
  frameElement: SketchpadFrameElement | null;
  theme: SketchpadTheme;
  queryClient: QueryClient;
  getSnapshot: () => SketchpadSnapshot;
  applyLocal: (ops: SketchpadOp[], opIds?: string[]) => void;
  reportCaret: (caret: SketchpadPresenceCaret | null) => void;
  events: SketchpadFrameEvents;
}

export interface SketchpadFrameHandle {
  srcDoc: string;
<<<<<<< HEAD
=======
  documentReady: boolean;
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  ready: boolean;
  post: (message: HostToSketchpadFrameMessage) => void;
  sendInit: (viewport: SketchpadViewport) => void;
  syncSnapshot: (
    prev: SketchpadSnapshot | null,
    next: SketchpadSnapshot,
  ) => void;
  setViewport: (viewport: SketchpadViewport) => void;
  setSelection: (ids: string[]) => void;
  setFocus: (id: string | null) => void;
  setBusy: (busy: boolean) => void;
  setCarets: (carets: SketchpadFrameCaret[]) => void;
}

export function useSketchpadFrame(
  options: UseSketchpadFrameOptions,
): SketchpadFrameHandle {
  const { frameElement } = options;
  const api = useSketchpadApi();
  const { vendoredSketchpadModules: vendoredModules } = useHostCapabilities();
  const srcDoc = useMemo(
    () => buildSketchpadFrameDocument({ vendoredModules }),
    [vendoredModules],
  );
<<<<<<< HEAD
=======
  const [documentReady, setDocumentReady] = useState(!vendoredModules);

  useEffect(() => {
    if (!vendoredModules) return;
    let cancelled = false;
    void resolveService<HostTrpcClient>(HOST_TRPC_CLIENT)
      .sketchpadFrame.registerDocument.mutate({
        html: srcDoc,
        csp: sketchpadFramePolicy(true),
      })
      .then(() => {
        if (!cancelled) setDocumentReady(true);
      })
      .catch((error: unknown) => {
        log.error("Could not register the board frame document", { error });
      });
    return () => {
      cancelled = true;
    };
  }, [srcDoc, vendoredModules]);
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  const [ready, setReady] = useState(false);
  const readyRef = useRef(false);

  const latest = useRef(options);
  latest.current = options;

  const fromFrame = useRef(new Map<string, string>());

  const postRaw = useCallback(
    (message: HostToSketchpadFrameMessage): void => {
      sendToSketchpadFrame(frameElement, message);
    },
    [frameElement],
  );

  const post = useCallback(
    (message: HostToSketchpadFrameMessage): void => {
      if (!readyRef.current) return;
      postRaw(message);
    },
    [postRaw],
  );

  const sendInit = useCallback(
    (viewport: SketchpadViewport): void => {
      const { theme, getSnapshot } = latest.current;
      const snapshot = getSnapshot();
      fromFrame.current.clear();
      postRaw({
        channel: SKETCHPAD_CHANNEL,
        type: "init",
        theme,
        viewport,
        fragments: snapshot.fragments,
        state: frameState(snapshot.state),
      });
    },
    [postRaw],
  );

  const syncSnapshot = useCallback(
    (prev: SketchpadSnapshot | null, next: SketchpadSnapshot): void => {
      const previousFragments = new Map(
        (prev?.fragments ?? []).map((fragment) => [fragment.id, fragment]),
      );
      for (const fragment of next.fragments) {
        const before = previousFragments.get(fragment.id);
        if (before && fragmentsEqual(before, fragment)) continue;
        post({
          channel: SKETCHPAD_CHANNEL,
          type: "upsert-fragment",
          fragment:
            before?.code === fragment.code
              ? { ...fragment, code: undefined }
              : fragment,
        });
      }
      const nextIds = new Set(next.fragments.map((fragment) => fragment.id));
      for (const id of previousFragments.keys()) {
        if (!nextIds.has(id)) {
          post({ channel: SKETCHPAD_CHANNEL, type: "remove-fragment", id });
        }
      }
      const prevState = prev?.state ?? {};
      const keys = new Set([
        ...Object.keys(prevState),
        ...Object.keys(next.state),
      ]);
      for (const key of keys) {
        const value = next.state[key] ?? null;
        if (value === (prevState[key] ?? null)) continue;
        const json = stableJson(value);
        if (stableJson(prevState[key] ?? null) === json) continue;
        if (fromFrame.current.get(key) === json) {
          fromFrame.current.delete(key);
          continue;
        }
        post({
          channel: SKETCHPAD_CHANNEL,
          type: "set-state",
          key,
          value: fieldMessageValue(value),
        });
      }
    },
    [post],
  );

  const sentCarets = useRef("");
  const setCarets = useCallback(
    (carets: SketchpadFrameCaret[]): void => {
<<<<<<< HEAD
      if (!readyRef.current) return;
=======
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
      const json = stableJson(carets);
      if (json === sentCarets.current) return;
      sentCarets.current = json;
      post({ channel: SKETCHPAD_CHANNEL, type: "set-carets", carets });
    },
    [post],
  );

  const setViewport = useCallback(
    (viewport: SketchpadViewport): void => {
      post({ channel: SKETCHPAD_CHANNEL, type: "set-viewport", viewport });
    },
    [post],
  );

  const setSelection = useCallback(
    (ids: string[]): void => {
      post({ channel: SKETCHPAD_CHANNEL, type: "set-selection", ids });
    },
    [post],
  );

  const setFocus = useCallback(
    (id: string | null): void => {
      post({ channel: SKETCHPAD_CHANNEL, type: "set-focus", id });
    },
    [post],
  );

  const setBusy = useCallback(
    (busy: boolean): void => {
      post({ channel: SKETCHPAD_CHANNEL, type: "set-busy", busy });
    },
    [post],
  );

  useLayoutEffect(() => {
<<<<<<< HEAD
    readyRef.current = false;
    setReady(false);
    fromFrame.current.clear();
    sentCarets.current = "";
    const budget = createSketchpadBudget(options.sketchpadId);
    const controller = new AbortController();
    const route = createSketchpadHostMessageRouter({
      post: postRaw,
      signal: controller.signal,
      callbacks: () => latest.current,
      budget,
      compiled: api.compiled.bind(api),
      hasUserActivation: () => navigator.userActivation?.isActive === true,
      openExternal: openExternalUrl,
      onReady: () => {
        readyRef.current = true;
        setReady(true);
      },
      onStateEcho: (key, value) =>
        fromFrame.current.set(key, stableJson(value)),
    });
=======
    let activeRequests = 0;
    let lastExternalOpen = 0;
    const controller = new AbortController();

    const reply = (
      id: string,
      ok: boolean,
      result?: unknown,
      error?: string,
    ): void => {
      if (controller.signal.aborted) return;
      postRaw({
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
      if (
        activeRequests >= MAX_PENDING_DATA_REQUESTS ||
        estimateJsonBytes(message.payload) >
          (message.method === "stateEditText"
            ? 2 * 1024 * 1024
            : MAX_DATA_REQUEST_BYTES)
      ) {
        reply(message.id, false, undefined, SKETCHPAD_TOO_MANY_READS_AT_ONCE);
        return;
      }
      activeRequests += 1;
      const { sketchpadId, queryClient, getSnapshot, applyLocal, reportCaret } =
        latest.current;
      const ctx: SketchpadDataBridgeContext = {
        sketchpadId,
        queryClient,
        getSnapshot,
        applyLocal,
        reportCaret,
        signal: controller.signal,
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
      message: Extract<
        SketchpadFrameToHostMessage,
        { type: "compile-request" }
      >,
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
          await api.compiled(
            options.sketchpadId,
            message.refs,
            controller.signal,
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
      const events = latest.current.events;
      switch (message.type) {
        case "compile-request":
          void runCompileRequest(message);
          break;
        case "ready":
          readyRef.current = true;
          setReady(true);
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
          if (!spendSketchpadWrite(options.sketchpadId)) {
            log.warn("Paused a fragment that writes shared state too fast");
            break;
          }
          if (isField(latest.current.getSnapshot().state[message.key])) break;
          fromFrame.current.set(message.key, stableJson(message.value ?? null));
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
          } else if (navigator.userActivation?.isActive !== true) {
            log.warn("Ignored fragment external URL open without interaction");
          } else if (now - lastExternalOpen < EXTERNAL_OPEN_MIN_INTERVAL_MS) {
            log.warn("Throttled fragment external URL open");
          } else {
            lastExternalOpen = now;
            openExternalUrl(message.url);
          }
          break;
        }
      }
    };

>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
    if (!frameElement) return;
    const stopListening = listenToSketchpadFrame(frameElement, (data) => {
      const parsed = sketchpadFrameToHostMessageSchema.safeParse(data);
      if (!parsed.success) return;
      route(parsed.data);
    });
    return () => {
      controller.abort();
      stopListening();
    };
<<<<<<< HEAD
  }, [frameElement, postRaw, api, options.sketchpadId]);
=======
  }, [frameElement, postRaw, options.sketchpadId, api]);
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)

  useEffect(() => {
    post({
      channel: SKETCHPAD_CHANNEL,
      type: "set-theme",
      theme: options.theme,
    });
  }, [post, options.theme]);

  return {
    srcDoc,
<<<<<<< HEAD
=======
    documentReady,
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
    ready,
    post,
    sendInit,
    syncSnapshot,
    setViewport,
    setSelection,
    setFocus,
    setBusy,
    setCarets,
  };
}

function frameState(state: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(state)) {
    out[key] = fieldMessageValue(value);
  }
  return out;
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? null) ?? "null";
  } catch {
    return "null";
  }
}
