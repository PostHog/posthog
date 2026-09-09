import type { SketchpadSummary } from "@posthog/shared";
import {
  sketchpadAsCanvas,
  useAllSketchpadsAsCanvases,
  useSpaceSketchpadsAsCanvases,
} from "@posthog/ui/features/sketchpad/hooks/useSketchpadsAsCanvases";
import {
  QueryClient,
  QueryClientProvider,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { flag, list } = vi.hoisted(() => ({ flag: vi.fn(), list: vi.fn() }));
vi.mock("@posthog/ui/features/feature-flags/useSketchpadsFlag", () => ({
  useSketchpadsFlag: flag,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    sketchpad: {
      list: {
        queryOptions: (
          input: { channelId?: string },
          options: UseQueryOptions,
        ) => ({
          ...options,
          queryKey: ["sketchpad", "list", input],
          queryFn: () => list(input),
        }),
      },
    },
  }),
}));

function summary(over: Partial<SketchpadSummary> = {}): SketchpadSummary {
  return {
    id: "board-1",
    name: "Status board",
    channelId: "space-1",
    createdAt: "2026-09-01T10:00:00Z",
    updatedAt: "2026-09-02T10:00:00Z",
    fragmentCount: 0,
    headSeq: 0,
    pinned: false,
    preview: [],
    ...over,
  };
}

describe("sketchpadAsCanvas", () => {
  afterEach(() => vi.useRealTimers());

  it.each([undefined, "", "space-1"])(
    "gates list requests for %s",
    async (channelId) => {
      vi.useFakeTimers();
      flag.mockReturnValue(false);
      list.mockReset().mockResolvedValue([summary()]);
      const client = new QueryClient();
      const useBoards =
        channelId === undefined
          ? useAllSketchpadsAsCanvases
          : useSpaceSketchpadsAsCanvases;
      const { result, rerender, unmount } = renderHook(
        () => useBoards(channelId),
        {
          wrapper: ({ children }: PropsWithChildren) =>
            createElement(QueryClientProvider, { client }, children),
        },
      );
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(list).not.toHaveBeenCalled();
      flag.mockReturnValue(true);
      rerender();
      await act(() => vi.advanceTimersByTimeAsync(1));
      if (channelId === "") {
        expect(list).not.toHaveBeenCalled();
      } else {
        expect(list).toHaveBeenCalledExactlyOnceWith({ channelId });
        expect(result.current.map((board) => board.id)).toEqual(["board-1"]);
      }
      flag.mockReturnValue(false);
      rerender();
      list.mockClear();
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(list).not.toHaveBeenCalled();
      expect(result.current).toEqual([]);
      unmount();
      client.clear();
    },
  );

  it("carries the creator and the last actor into the row", () => {
    const record = sketchpadAsCanvas(
      summary({
        createdBy: {
          kind: "user",
          userId: 7,
          userUuid: "creator-uuid",
          userName: "Ada",
          userEmail: "ada@example.com",
        },
        lastActor: {
          kind: "user",
          userId: 9,
          userUuid: "actor-uuid",
          userName: "Grace",
          userEmail: "grace@example.com",
        },
      }),
    );

    expect(record.createdBy).toBe("Ada");
    expect(record.createdByUuid).toBe("creator-uuid");
    expect(record.createdByEmail).toBe("ada@example.com");
    expect(record.lastActor).toEqual({
      name: "Grace",
      uuid: "actor-uuid",
      email: "grace@example.com",
    });
  });
});
