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
  it.each([
    { fullPath: "/settings/$category", params: { category: "general" } },
    { fullPath: "/settings/", params: {} },
  ])("maps the settings route $fullPath to the settings view", (match) => {
    mocks.matches = [match];
    expect(getAppViewSnapshot()).toEqual({ type: "settings" });
  });
});
