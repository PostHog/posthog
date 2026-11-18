import { afterEach, describe, expect, it, vi } from "vitest";
import { shouldFocusOnBackgroundClick } from "./backgroundClick";

const IGNORE_SELECTOR = 'button, [contenteditable="true"]';

function mockSelection(isCollapsed: boolean | null): void {
  vi.spyOn(window, "getSelection").mockReturnValue(
    isCollapsed === null ? null : ({ isCollapsed } as Selection),
  );
}

describe("shouldFocusOnBackgroundClick", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    {
      gesture: "a plain click on background chrome",
      tagName: "div",
      isCollapsed: true,
      expected: true,
    },
    {
      gesture: "releasing a drag-select outside the input",
      tagName: "div",
      isCollapsed: false,
      expected: false,
    },
    {
      gesture: "a click on an element that answers clicks itself",
      tagName: "button",
      isCollapsed: true,
      expected: false,
    },
    {
      gesture: "a click with no selection object at all",
      tagName: "div",
      isCollapsed: null,
      expected: true,
    },
  ])("returns $expected for $gesture", ({ tagName, isCollapsed, expected }) => {
    const target = document.createElement(tagName);
    document.body.replaceChildren(target);
    mockSelection(isCollapsed);

    expect(shouldFocusOnBackgroundClick(target, IGNORE_SELECTOR)).toBe(
      expected,
    );
  });
});
