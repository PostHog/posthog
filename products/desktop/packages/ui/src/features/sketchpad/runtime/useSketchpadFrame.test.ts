import {
  emptySketchpadSnapshot,
  SKETCHPAD_CHANNEL,
  SKETCHPAD_FRAME_TO_HOST_CHANNEL,
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
  );
  act(() =>
    sendFromFrame(frame, { channel: SKETCHPAD_CHANNEL, type: "ready" }),
  );
  send.mockClear();
  return { frame, send, result, unmount, queryClient, rerender };
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
    surface: "card" as const,
    hidden: false,
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
});
