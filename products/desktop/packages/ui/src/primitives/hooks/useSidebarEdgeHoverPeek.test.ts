import {
  PEEK_CLOSE_MARGIN,
  PEEK_REVEAL_THRESHOLD,
  shouldCloseOnExit,
  shouldRevealOnEdge,
} from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { describe, expect, it } from "vitest";

describe("shouldRevealOnEdge", () => {
  const threshold = PEEK_REVEAL_THRESHOLD;

  it.each([
    ["crosses into the zone from outside", 10, false, true],
    ["already inside the zone (no re-trigger)", 10, true, false],
    ["outside the zone", 100, false, false],
    ["flick from outside straight to the edge in one sample", 0, false, true],
    ["exactly on the threshold, crossing in", threshold, false, true],
    ["just past the threshold", threshold + 1, false, false],
  ])("%s", (_name, pointer, wasInside, expected) => {
    expect(shouldRevealOnEdge({ pointer, wasInside, threshold })).toBe(
      expected,
    );
  });
});

describe("shouldCloseOnExit", () => {
  const margin = PEEK_CLOSE_MARGIN;

  it.each([
    ["inside the panel", 100, 240, false],
    ["between the panel edge and the margin", 280, 240, false],
    ["exactly on the far edge (right edge)", 240, 240, false],
    ["exactly on the close boundary", 240 + margin, 240, false],
    ["past the close boundary into content", 240 + margin + 1, 240, true],
    ["stays open at the left edge / off-window", 0, 240, false],
    ["wide panel still open before its boundary", 400 + margin, 400, false],
    ["wide panel closes past its boundary", 400 + margin + 1, 400, true],
  ])("%s", (_name, pointer, width, expected) => {
    expect(shouldCloseOnExit({ pointer, width, margin })).toBe(expected);
  });
});
