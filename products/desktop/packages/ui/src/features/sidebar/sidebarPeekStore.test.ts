import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  beginSidebarPeek,
  cancelSidebarPeek,
  endSidebarPeek,
  holdSidebarPeek,
  releaseSidebarPeek,
  useSidebarPeekStore,
} from "./sidebarPeekStore";

const isPeeked = (): boolean => useSidebarPeekStore.getState().peek;

describe("sidebarPeekStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset shared module-level state (hold count + hide timer + peek) so each
    // case starts clean.
    cancelSidebarPeek();
  });

  afterEach(() => {
    cancelSidebarPeek();
    vi.useRealTimers();
  });

  it("endSidebarPeek hides the peek only once the delay elapses", () => {
    beginSidebarPeek();
    expect(isPeeked()).toBe(true);

    endSidebarPeek(200);
    expect(isPeeked()).toBe(true);

    vi.advanceTimersByTime(200);
    expect(isPeeked()).toBe(false);
  });

  it("keeps the peek open while held, then closes once released", () => {
    beginSidebarPeek();
    holdSidebarPeek();

    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(true);

    releaseSidebarPeek();
    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(false);
  });

  it("keeps the peek held until every holder has released", () => {
    beginSidebarPeek();
    holdSidebarPeek();
    holdSidebarPeek();

    releaseSidebarPeek();
    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(true);

    releaseSidebarPeek();
    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(false);
  });

  it("releaseSidebarPeek without a hold does not break a later hold", () => {
    releaseSidebarPeek();

    beginSidebarPeek();
    holdSidebarPeek();
    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(true);
  });

  it("holdSidebarPeek cancels a hide that is already pending", () => {
    beginSidebarPeek();
    endSidebarPeek(200);
    holdSidebarPeek();

    vi.advanceTimersByTime(200);
    expect(isPeeked()).toBe(true);
  });

  it("cancelSidebarPeek closes immediately and clears the hold", () => {
    beginSidebarPeek();
    holdSidebarPeek();

    cancelSidebarPeek();
    expect(isPeeked()).toBe(false);

    // The hold was cleared, so normal begin/end behaviour resumes.
    beginSidebarPeek();
    endSidebarPeek(0);
    vi.runAllTimers();
    expect(isPeeked()).toBe(false);
  });
});
