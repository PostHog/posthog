import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getRouterOrNull: vi.fn(),
}));

vi.mock("./routerRef", () => ({
  getRouterOrNull: mocks.getRouterOrNull,
}));

import {
  navigateToChannelNewTask,
  navigateToNewTask,
} from "./navigationBridge";

type StateUpdater = (prev: Record<string, unknown>) => Record<string, unknown>;

// The composer screens key their draft session on `state.tabId`
// (getTaskInputSessionId) and remount on that key. A new-task entry born
// without the tag gets stamped by the tab strip a beat later, which flips the
// key and remounts the composer AFTER it consumed the one-shot prefill — the
// prompt handed to openTaskInput (a posthog-code://new?prompt= deep link, a
// show_actions compose button) silently vanished. These pin the entry to be
// born already tagged with the tab it stays in.
describe("new-task navigation carries the tab tag", () => {
  const navigate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRouterOrNull.mockReturnValue({ navigate });
  });

  it("navigateToNewTask preserves the current entry's tabId", () => {
    navigateToNewTask();

    expect(navigate).toHaveBeenCalledTimes(1);
    const { to, state } = navigate.mock.calls[0][0];
    expect(to).toBe("/new");
    expect((state as StateUpdater)({ tabId: "tab-1" })).toEqual({
      tabId: "tab-1",
    });
  });

  it("navigateToChannelNewTask preserves the current entry's tabId", () => {
    navigateToChannelNewTask("chan-1");

    expect(navigate).toHaveBeenCalledTimes(1);
    const call = navigate.mock.calls[0][0];
    expect(call.to).toBe("/spaces/$channelId/new");
    expect(call.params).toEqual({ channelId: "chan-1" });
    expect((call.state as StateUpdater)({ tabId: "tab-9" })).toEqual({
      tabId: "tab-9",
    });
  });

  // Route-scoped state (loopListOrigin, inboxBackOrigin) describes the entry
  // being left; only the tab tag may survive onto the new-task entry.
  it("carries only the tab tag, not other state keys", () => {
    navigateToNewTask();

    const { state } = navigate.mock.calls[0][0];
    expect(
      (state as StateUpdater)({ tabId: "tab-1", loopListOrigin: "loops" }),
    ).toEqual({ tabId: "tab-1" });
  });

  it("leaves an untagged entry untagged", () => {
    navigateToNewTask();

    const { state } = navigate.mock.calls[0][0];
    expect((state as StateUpdater)({})).toEqual({});
  });

  it("degrades to a no-op when the router is not mounted", () => {
    mocks.getRouterOrNull.mockReturnValue(null);

    expect(() => navigateToNewTask()).not.toThrow();
    expect(() => navigateToChannelNewTask("chan-1")).not.toThrow();
    expect(navigate).not.toHaveBeenCalled();
  });
});
