import {
  emptySketchpadSnapshot,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_FRAME_TO_HOST_CHANNEL,
<<<<<<< HEAD
=======
  SKETCHPAD_HOST_TO_FRAME_CHANNEL,
  type SketchpadDataMethod,
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  type SketchpadFrameToHostMessage,
  type SketchpadSnapshot,
} from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SketchpadWebviewElement } from "./sketchpadFrameElement";
import { useSketchpadFrame } from "./useSketchpadFrame";

vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ vendoredSketchpadModules: false }),
}));

const compiled = vi.fn();
const compileApi = { compiled };
vi.mock("@posthog/ui/features/sketchpad/hooks/useSketchpadApi", () => ({
  useSketchpadApi: () => compileApi,
}));

const query = vi.fn();
vi.mock("@posthog/ui/features/canvas/hostClient", () => ({
  hostClient: () => ({ canvasData: { query: { mutate: query } } }),
}));

function sendFromFrame(
  frame: SketchpadWebviewElement,
  message: SketchpadFrameToHostMessage,
): void {
  frame.dispatchEvent(
    Object.assign(new Event("ipc-message"), {
      channel: SKETCHPAD_FRAME_TO_HOST_CHANNEL,
      args: [message],
    }),
  );
}

function mountFrame(snapshot: SketchpadSnapshot, sketchpadId = "board") {
  const send = vi.fn();
  const frame = document.createElement("webview") as SketchpadWebviewElement;
  frame.send = send;
  const queryClient = new QueryClient();
<<<<<<< HEAD
  const { result, unmount, rerender } = renderHook(
    ({ element }) =>
      useSketchpadFrame({
        sketchpadId,
        frameElement: element,
        theme: "light",
        queryClient,
        getSnapshot: () => snapshot,
        applyLocal: vi.fn(),
        reportCaret: vi.fn(),
        events: {
          onExitFocus: vi.fn(),
          onReady: vi.fn(),
          onFragmentRendered: vi.fn(),
          onFragmentError: vi.fn(),
          onStateChanged: vi.fn(),
          onWheel: vi.fn(),
          onBackgroundPointer: vi.fn(),
          onFragmentPointerDown: vi.fn(),
          onPointerMove: vi.fn(),
          onPointerLeave: vi.fn(),
        },
      }),
    { initialProps: { element: frame } },
=======
  const { result, unmount } = renderHook(() =>
    useSketchpadFrame({
      sketchpadId,
      frameElement: frame,
      theme: "light",
      queryClient,
      getSnapshot: () => snapshot,
      applyLocal: vi.fn(),
      reportCaret: vi.fn(),
      events: {
        onExitFocus: vi.fn(),
        onReady: vi.fn(),
        onFragmentRendered: vi.fn(),
        onFragmentError: vi.fn(),
        onStateChanged: vi.fn(),
        onWheel: vi.fn(),
        onBackgroundPointer: vi.fn(),
        onFragmentPointerDown: vi.fn(),
        onPointerMove: vi.fn(),
        onPointerLeave: vi.fn(),
      },
    }),
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  );
  act(() =>
    sendFromFrame(frame, { channel: SKETCHPAD_CHANNEL, type: "ready" }),
  );
  send.mockClear();
<<<<<<< HEAD
  return { frame, send, result, unmount, queryClient, rerender };
=======
  return { frame, send, result, unmount, queryClient };
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
}

it("limits compilation requests and cancels them when the frame closes", async () => {
  const { frame, send, unmount, queryClient } = mountFrame(
    emptySketchpadSnapshot(),
  );
  let complete!: (value: object) => void;
  compiled.mockReset().mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const message = {
    channel: SKETCHPAD_CHANNEL,
    type: "compile-request",
    id: "first",
    refs: ["a".repeat(64)],
  } satisfies SketchpadFrameToHostMessage;
  await act(async () => {
    sendFromFrame(frame, message);
    sendFromFrame(frame, { ...message, id: "second" });
  });
  expect(compiled).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][1]).toMatchObject({ id: "second", ok: false });
  const signal = compiled.mock.calls[0][2] as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => complete({}));
  expect(send).toHaveBeenCalledTimes(1);
  queryClient.clear();
});

<<<<<<< HEAD
=======
it.each([false, true])(
  "bounds queued reads and handles a closed frame: %s",
  async (close) => {
    vi.useFakeTimers();
    const { frame, send, unmount, queryClient } = mountFrame(
      emptySketchpadSnapshot(),
      `read-queue-${close}`,
    );
    let active = 0;
    let peak = 0;
    query.mockReset().mockImplementation(() => {
      peak = Math.max(peak, ++active);
      return new Promise((resolve) =>
        setTimeout(() => {
          active--;
          resolve({ results: [] });
        }, 20_000),
      );
    });
    try {
      await act(async () => {
        for (let index = 0; index < 16; index++) {
          sendFromFrame(frame, {
            channel: SKETCHPAD_CHANNEL,
            type: "data-request",
            id: String(index),
            method: "query",
            payload: { hogql: `select ${index}` },
          });
        }
      });
      expect(query).toHaveBeenCalledTimes(8);
      if (close) unmount();
      await act(() => vi.advanceTimersByTimeAsync(40_000));
      expect(peak).toBe(8);
      expect(query).toHaveBeenCalledTimes(close ? 8 : 16);
      const replies = send.mock.calls
        .map(([, message]) => message)
        .filter((message) => message.type === "data-response");
      expect(replies).toHaveLength(close ? 0 : 16);
      expect(replies.every((message) => message.ok)).toBe(true);
    } finally {
      unmount();
      queryClient.clear();
      vi.useRealTimers();
    }
  },
);

>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
it("sends changed data without repeating unchanged source or state", () => {
  const toJSON = vi.fn(() => ({ value: "unchanged" }));
  const fragment = {
    id: "moved",
    x: 0,
    y: 0,
    w: 360,
    h: 240,
    z: 0,
    code: "export default () => null",
    codeVersion: 1,
<<<<<<< HEAD
    surface: "card" as const,
    hidden: false,
=======
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
  };
  const previous = {
    schemaVersion: 1 as const,
    fragments: [
      fragment,
      { ...fragment, id: "edited" },
      { ...fragment, id: "removed" },
    ],
    state: {
      unchanged: { toJSON },
      changed: 1,
      removed: true,
      equal: { value: 1 },
    },
  };
  const { send, result } = mountFrame(previous);

  result.current.syncSnapshot(previous, {
    ...previous,
    fragments: [
      { ...fragment, x: 100 },
      {
        ...fragment,
        id: "edited",
        code: "export default () => 'new'",
        codeVersion: 2,
      },
      { ...fragment, id: "added" },
    ],
    state: {
      unchanged: previous.state.unchanged,
      changed: 2,
      equal: { value: 1 },
    },
  });

  expect(toJSON).not.toHaveBeenCalled();
  expect(send.mock.calls.map(([, message]) => message)).toEqual([
    {
      channel: SKETCHPAD_CHANNEL,
      type: "upsert-fragment",
      fragment: { ...fragment, x: 100, code: undefined },
    },
    {
      channel: SKETCHPAD_CHANNEL,
      type: "upsert-fragment",
      fragment: {
        ...fragment,
        id: "edited",
        code: "export default () => 'new'",
        codeVersion: 2,
      },
    },
    {
      channel: SKETCHPAD_CHANNEL,
      type: "upsert-fragment",
      fragment: { ...fragment, id: "added" },
    },
    { channel: SKETCHPAD_CHANNEL, type: "remove-fragment", id: "removed" },
    { channel: SKETCHPAD_CHANNEL, type: "set-state", key: "changed", value: 2 },
    {
      channel: SKETCHPAD_CHANNEL,
      type: "set-state",
      key: "removed",
      value: null,
    },
  ]);
});

<<<<<<< HEAD
it("resets readiness and caret delivery when the frame element changes", () => {
  const { result, rerender, unmount, queryClient } = mountFrame(
    emptySketchpadSnapshot(),
  );
  const carets = [
    {
      clientId: "person",
      key: "note",
      anchor: null,
      focus: null,
      name: "Person",
      color: "#000000",
      textColor: "#ffffff",
    },
  ];
  result.current.setCarets(carets);
  const frame = document.createElement("webview") as SketchpadWebviewElement;
  frame.send = vi.fn();
  rerender({ element: frame });
  expect(result.current.ready).toBe(false);
  result.current.setCarets(carets);
  expect(frame.send).not.toHaveBeenCalled();
  act(() =>
    sendFromFrame(frame, { channel: SKETCHPAD_CHANNEL, type: "ready" }),
  );
  result.current.setCarets(carets);
  expect(frame.send).toHaveBeenCalledWith(
    "posthog-sketchpad-host",
    expect.objectContaining({ type: "set-carets", carets }),
  );
  unmount();
  queryClient.clear();
=======
it.each<[SketchpadDataMethod, number, boolean]>([
  ["stateEditText", 20_000, true],
  ["stateEditText", 60_000, false],
  ["query", 20_000, false],
])("bounds %s requests with %i entry IDs", async (method, count, ok) => {
  const { frame, send } = mountFrame(emptySketchpadSnapshot());
  await act(async () => {
    sendFromFrame(frame, {
      channel: SKETCHPAD_CHANNEL,
      type: "data-request",
      id: "request",
      method,
      payload: {
        key: "note",
        base: "a".repeat(count),
        next: "b".repeat(count),
        baseIds: Array.from(
          { length: count },
          (_, index) => `${"a".repeat(32)}-${index}`,
        ),
      },
    });
  });
  expect(send).toHaveBeenCalledWith(
    SKETCHPAD_HOST_TO_FRAME_CHANNEL,
    expect.objectContaining({
      type: "data-response",
      id: "request",
      ok,
    }),
  );
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
});
