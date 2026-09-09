import {
  emptySketchpadSnapshot,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_FRAME_TO_HOST_CHANNEL,
  SKETCHPAD_HOST_TO_FRAME_CHANNEL,
  type SketchpadDataMethod,
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
  );
  act(() =>
    sendFromFrame(frame, { channel: SKETCHPAD_CHANNEL, type: "ready" }),
  );
  send.mockClear();
  return { frame, send, result, unmount, queryClient };
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
});
