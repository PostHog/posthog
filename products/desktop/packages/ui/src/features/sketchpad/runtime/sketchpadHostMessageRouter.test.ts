import {
  emptySketchpadSnapshot,
  SKETCHPAD_CHANNEL,
  type SketchpadDataMethod,
  type SketchpadSnapshot,
} from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { SKETCHPAD_REQUEST_TOO_LARGE } from "../sketchpadCopy";
import { createSketchpadBudget } from "./sketchpadDataBridge";
import { createSketchpadHostMessageRouter } from "./sketchpadHostMessageRouter";

const query = vi.fn();
vi.mock("@posthog/ui/features/canvas/hostClient", () => ({
  hostClient: () => ({ canvasData: { query: { mutate: query } } }),
}));

async function flush(run: () => unknown): Promise<void> {
  await run();
}

function mountRouter(snapshot: SketchpadSnapshot, sketchpadId = "board") {
  const send = vi.fn();
  const controller = new AbortController();
  const queryClient = new QueryClient();
  const frame = createSketchpadHostMessageRouter({
    post: send,
    signal: controller.signal,
    budget: createSketchpadBudget(sketchpadId),
    compiled: vi.fn(),
    callbacks: () => ({
      sketchpadId,
      frameElement: null,
      theme: "light",
      queryClient,
      getSnapshot: () => snapshot,
      applyLocal: vi.fn(),
      reportCaret: vi.fn(),
      events: {
        onReady: vi.fn(),
        onExitFocus: vi.fn(),
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
    hasUserActivation: () => false,
    openExternal: vi.fn(),
    onReady: vi.fn(),
    onStateEcho: vi.fn(),
  });
  return { frame, send, queryClient, unmount: () => controller.abort() };
}

it.each([false, true])(
  "bounds queued reads and handles a closed frame: %s",
  async (close) => {
    vi.useFakeTimers();
    const { frame, send, unmount, queryClient } = mountRouter(
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
      await flush(async () => {
        for (let index = 0; index < 16; index++) {
          frame({
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
      await flush(() => vi.advanceTimersByTimeAsync(40_000));
      expect(peak).toBe(8);
      expect(query).toHaveBeenCalledTimes(close ? 8 : 16);
      const replies = send.mock.calls
        .map(([message]) => message)
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

it.each<[SketchpadDataMethod, number, boolean]>([
  ["stateEditText", 20_000, true],
  ["stateEditText", 60_000, false],
  ["query", 20_000, false],
])("bounds %s requests with %i entry IDs", async (method, count, ok) => {
  const { frame, send } = mountRouter(emptySketchpadSnapshot());
  await flush(async () => {
    frame({
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
  await vi.waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "data-response",
        id: "request",
        ok,
        ...(ok ? {} : { error: SKETCHPAD_REQUEST_TOO_LARGE }),
      }),
    ),
  );
});
