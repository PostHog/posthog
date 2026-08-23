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
      html: '<div id="target"></div>',
      isCollapsed: true,
      expected: true,
    },
    {
      // Releasing a drag-select outside the input targets the container, so
      // the ignore selector never matches and only the live selection tells
      // the two gestures apart.
      gesture: "releasing a drag-select outside the input",
      html: '<div id="target"></div>',
      isCollapsed: false,
      expected: false,
    },
    {
      gesture: "a click on an element that answers clicks itself",
      html: '<button id="target" type="button"></button>',
      isCollapsed: true,
      expected: false,
    },
    {
      gesture: "a click with no selection object at all",
      html: '<div id="target"></div>',
      isCollapsed: null,
      expected: true,
    },
  ])("returns $expected for $gesture", ({ html, isCollapsed, expected }) => {
    document.body.innerHTML = html;
    mockSelection(isCollapsed);

    const target = document.getElementById("target") as HTMLElement;

    expect(shouldFocusOnBackgroundClick(target, IGNORE_SELECTOR)).toBe(
      expected,
    );
  });
});
