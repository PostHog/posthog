import { buildSketchpadFrameDocument } from "@posthog/core/sketchpad/frameDocument";
import {
  fragmentsEqual,
  type HostToSketchpadFrameMessage,
  SKETCHPAD_CHANNEL,
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
import { fieldMessageValue } from "@posthog/ui/features/sketchpad/runtime/sketchpadFieldMessages";
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
import { createSketchpadBudget } from "./sketchpadDataBridge";
import {
  listenToSketchpadFrame,
  type SketchpadFrameElement,
  sendToSketchpadFrame,
} from "./sketchpadFrameElement";
import { createSketchpadHostMessageRouter } from "./sketchpadHostMessageRouter";

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
      if (!readyRef.current) return;
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
  }, [frameElement, postRaw, api, options.sketchpadId]);

  useEffect(() => {
    post({
      channel: SKETCHPAD_CHANNEL,
      type: "set-theme",
      theme: options.theme,
    });
  }, [post, options.theme]);

  return {
    srcDoc,
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
