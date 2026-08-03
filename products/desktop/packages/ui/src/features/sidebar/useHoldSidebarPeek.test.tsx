import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  beginSidebarPeek,
  cancelSidebarPeek,
  endSidebarPeek,
  holdSidebarPeek,
  useSidebarPeekStore,
} from "./sidebarPeekStore";
import { useHoldSidebarPeek } from "./useHoldSidebarPeek";

const isPeeked = (): boolean => useSidebarPeekStore.getState().peek;

const expectPeekAfterEnd = (expected: boolean): void => {
  endSidebarPeek(0);
  act(() => {
    vi.runAllTimers();
  });
  expect(isPeeked()).toBe(expected);
};

describe("useHoldSidebarPeek", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    cancelSidebarPeek();
  });

  afterEach(() => {
    cancelSidebarPeek();
    vi.useRealTimers();
  });

  it("holds while open and releases on close", () => {
    beginSidebarPeek();
    const { result } = renderHook(() => useHoldSidebarPeek());

    act(() => result.current(true));
    expectPeekAfterEnd(true);

    act(() => result.current(false));
    expectPeekAfterEnd(false);
  });

  it("releases on unmount while open", () => {
    beginSidebarPeek();
    const { result, unmount } = renderHook(() => useHoldSidebarPeek());

    act(() => result.current(true));
    unmount();
    expectPeekAfterEnd(false);
  });

  it("unmounting without opening leaves another holder's hold intact", () => {
    beginSidebarPeek();
    holdSidebarPeek();
    const { unmount } = renderHook(() => useHoldSidebarPeek());

    unmount();
    expectPeekAfterEnd(true);
  });

  it("repeated open events acquire a single hold", () => {
    beginSidebarPeek();
    const { result } = renderHook(() => useHoldSidebarPeek());

    act(() => result.current(true));
    act(() => result.current(true));
    act(() => result.current(false));
    expectPeekAfterEnd(false);
  });
});
