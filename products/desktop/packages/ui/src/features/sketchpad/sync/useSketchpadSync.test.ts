import type { SketchpadApi } from "@posthog/core/sketchpad/sketchpadSync";
import { emptySketchpadSnapshot } from "@posthog/shared";
import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type SketchpadSyncActorUser,
  useSketchpadSync,
} from "./useSketchpadSync";

function setup() {
  let seq = 0;
  const api = {
    get: vi.fn<SketchpadApi["get"]>().mockImplementation(async (id) => ({
      id,
      name: id,
      channelId: "space",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      snapshot: emptySketchpadSnapshot(),
      headSeq: 0,
    })),
    opsSince: vi
      .fn<SketchpadApi["opsSince"]>()
      .mockResolvedValue({ headSeq: 0, results: [] }),
    appendOps: vi
      .fn<SketchpadApi["appendOps"]>()
      .mockImplementation(async (_id, input) => {
        const results = input.ops.map(({ opId }) => ({ opId, seq: ++seq }));
        return { headSeq: seq, results };
      }),
  };
  const render = vi.fn();
  const initialProps: {
    sketchpadId: string;
    actorUser?: SketchpadSyncActorUser;
  } = {
    sketchpadId: "first",
  };
  const hook = renderHook(
    ({ sketchpadId, actorUser }) => {
      render();
      return useSketchpadSync(sketchpadId, api, actorUser);
    },
    { initialProps },
  );
  return { api, render, ...hook };
}

describe("useSketchpadSync", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    registerRendererStateStorage({
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    });
  });
  afterEach(() => vi.useRealTimers());

  it("waits for the user identity and keeps pending edits when the name changes", async () => {
    const { api, result, rerender } = setup();
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(api.get).not.toHaveBeenCalled();

    rerender({
      sketchpadId: "first",
      actorUser: { userId: 7, userName: "Test user" },
    });
    await act(() => vi.advanceTimersByTimeAsync(0));
    const client = result.current.client;
    act(() =>
      client.applyLocal([{ type: "set_state", key: "first", value: true }]),
    );
    rerender({
      sketchpadId: "first",
      actorUser: { userId: 7, userName: "New name" },
    });
    act(() =>
      result.current.client.applyLocal([
        { type: "set_state", key: "second", value: true },
      ]),
    );

    expect(result.current.client).toBe(client);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(result.current.state.pending).toHaveLength(2);
    expect(result.current.state.pending[1].actor.userId).toBe(7);
    await act(() => client.flush());
  });

  it("does not render updates from a previous board", async () => {
    const { result, rerender, render } = setup();
    rerender({ sketchpadId: "first", actorUser: { userId: 7 } });
    await act(() => vi.advanceTimersByTimeAsync(0));
    const previous = result.current.client;
    rerender({ sketchpadId: "second", actorUser: { userId: 7 } });
    await act(() => vi.advanceTimersByTimeAsync(0));
    const renders = render.mock.calls.length;

    act(() => previous.setName("Late update"));

    expect(render).toHaveBeenCalledTimes(renders);
    expect(result.current.state).toMatchObject({
      sketchpadId: "second",
      name: "second",
    });
  });
});
