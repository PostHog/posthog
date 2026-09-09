import {
  type SketchpadApi,
  SketchpadSyncClient,
} from "@posthog/core/sketchpad/sketchpadSync";
import type { SketchpadLogEntry } from "@posthog/shared";
import { emptySketchpadSnapshot } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSketchpadCache } from "./useSketchpadCache";

const { write, host } = vi.hoisted(() => {
  const write = vi.fn().mockResolvedValue(undefined);
  return { write, host: { sketchpadCache: { write: { mutate: write } } } };
});

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => host,
}));

function entry(seq: number): SketchpadLogEntry {
  return {
    seq,
    opId: `op-${seq}`,
    actor: { kind: "user", userId: 2 },
    createdAt: "2026-01-01T00:00:00.000Z",
    op: { type: "set_state", key: `key-${seq}`, value: seq },
  };
}

async function setup() {
  const api = {
    get: vi.fn<SketchpadApi["get"]>().mockResolvedValue({
      id: "board",
      name: "Sketchpad",
      channelId: "space",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      snapshot: { ...emptySketchpadSnapshot(), state: { "key-1": 1 } },
      headSeq: 1,
<<<<<<< HEAD
      historyStartSeq: 0,
      historySnapshot: emptySketchpadSnapshot(),
=======
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
    }),
    opsSince: vi.fn<SketchpadApi["opsSince"]>().mockResolvedValue({
      headSeq: 1,
      results: [],
<<<<<<< HEAD
      historyStartSeq: 0,
      historySnapshot: emptySketchpadSnapshot(),
=======
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
    }),
    appendOps: vi.fn<SketchpadApi["appendOps"]>(),
  };
  const client = new SketchpadSyncClient(api, "board", {
    now: () => 0,
  });
  await client.load();
  const hook = renderHook(
    (state) => useSketchpadCache(state.sketchpadId, state),
    {
      initialProps: client.getState(),
    },
  );
  await tick();
  return { api, client, ...hook };
}

async function tick() {
  await act(() => vi.advanceTimersByTimeAsync(500));
}

describe("useSketchpadCache", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => vi.useRealTimers());

  it.each(["poll", "stream"] as const)(
    "writes a rename but skips unchanged %s data",
    async (source) => {
      const { client, rerender } = await setup();
      const snapshot = client.getState().snapshot;
      for (let poll = 0; poll < 3; poll++) {
        if (source === "poll") await client.poll();
        else client.ingestStreamEntry(entry(1));
        rerender(client.getState());
        await tick();
      }
      expect(client.getState().snapshot).toBe(snapshot);
      expect(write).toHaveBeenCalledTimes(1);

      client.setName("Renamed board");
      rerender(client.getState());
      await tick();

      expect(write).toHaveBeenCalledTimes(2);
      expect(write.mock.lastCall?.[0].name).toBe("Renamed board");
    },
  );

  it("waits for a missing operation before writing a new head", async () => {
    const { api, client, rerender } = await setup();
    api.opsSince.mockRejectedValue(new Error("Disconnected"));
    client.ingestStreamEntry(entry(3));
    rerender(client.getState());
    await tick();
    expect(write).toHaveBeenCalledTimes(1);

<<<<<<< HEAD
    api.opsSince.mockResolvedValue({
      headSeq: 3,
      results: [entry(2)],
      historyStartSeq: 0,
      historySnapshot: emptySketchpadSnapshot(),
    });
=======
    api.opsSince.mockResolvedValue({ headSeq: 3, results: [entry(2)] });
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
    await client.poll();
    rerender(client.getState());
    await tick();

    expect(write).toHaveBeenCalledTimes(2);
    expect(write.mock.lastCall?.[0]).toMatchObject({
      headSeq: 3,
      snapshot: { state: { "key-1": 1, "key-2": 2, "key-3": 3 } },
    });
  });
});
