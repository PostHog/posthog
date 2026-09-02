import { niceCeil } from "@posthog/core/billing/spendLimits";
import { describe, expect, it } from "vitest";
import { clampSpendLine, resolveScale, sliderStep } from "./SpendLimitSlider";

describe("SpendLimitSlider", () => {
  it.each([
    [55, 100],
    [100, 100],
    [101, 200],
    [440, 500],
    [7, 10],
    [1.4, 2],
    [0, 100],
  ] as const)("niceCeil(%s) -> %s", (value, expected) => {
    expect(niceCeil(value)).toBe(expected);
  });

  it("keeps the scale stable across small edits", () => {
    const scale = resolveScale(null, 55);
    expect(scale).toBe(100);
    // Lowering a line a bit must not rescale the track.
    expect(resolveScale(scale, 44)).toBe(100);
    // Passing the top grows it immediately.
    expect(resolveScale(scale, 130)).toBe(200);
    // Only a large drop shrinks it back.
    expect(resolveScale(scale, 12)).toBe(20);
  });

  it.each([
    [25, 0.5],
    [100, 1],
    [500, 5],
    [1200, 10],
  ] as const)("scale %s -> step %s", (scale, step) => {
    expect(sliderStep(scale)).toBe(step);
  });

  it("never lets the warning line pass the stop line, and vice versa", () => {
    expect(clampSpendLine("warn", 80, 50)).toBe(50);
    expect(clampSpendLine("warn", 30, 50)).toBe(30);
    expect(clampSpendLine("stop", 10, 20)).toBe(20);
    expect(clampSpendLine("stop", 60, 20)).toBe(60);
    expect(clampSpendLine("warn", 80, null)).toBe(80);
  });
});
