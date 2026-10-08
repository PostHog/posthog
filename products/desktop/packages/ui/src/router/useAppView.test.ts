import { describe, expect, it, vi } from "vitest";

type Match = { fullPath: string; params: Record<string, string | undefined> };

const mocks = vi.hoisted(() => ({ matches: [] as Match[] }));

vi.mock("./navigationBridge", () => ({
  getCurrentMatches: () => mocks.matches,
}));

import { getAppViewSnapshot } from "./useAppView";

// The view is derived by switching on a match's `fullPath`. The pathless
// `_shell` layout lives only in a route's id, never its fullPath, so a case
// written in id form silently never matches and settings falls through to the
// task-input view.
describe("getAppViewSnapshot", () => {
  it("treats the canonical report as its own view, not a task or Inbox", () => {
    mocks.matches = [
      { fullPath: "/reports/$reportId", params: { reportId: "report-1" } },
    ];
    expect(getAppViewSnapshot()).toEqual({ type: "report" });
  });
  // A route missing from the switch falls through to the task-input view, which
  // is outside the browser tab's label vocabulary. The tab then keeps the label
  // of the page you came from.
  it("gives the canvases page its own view", () => {
    mocks.matches = [{ fullPath: "/canvases", params: {} }];
    expect(getAppViewSnapshot()).toEqual({ type: "canvases" });
  });
  it.each([
    { fullPath: "/settings/$category", params: { category: "general" } },
    { fullPath: "/settings/", params: {} },
  ])("maps the settings route $fullPath to the settings view", (match) => {
    mocks.matches = [match];
    expect(getAppViewSnapshot()).toEqual({ type: "settings" });
  });
});
