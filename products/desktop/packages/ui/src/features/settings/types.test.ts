import { describe, expect, it } from "vitest";
import { isSettingsCategory, resolveSettingsCategory } from "./types";

describe("isSettingsCategory", () => {
  it("recognizes sidebar experience settings", () => {
    expect(isSettingsCategory("sidebar")).toBe(true);
  });
});

describe("resolveSettingsCategory", () => {
  it.each([
    ["sidebar", "sidebar"],
    // Startup restores the last URL, so dropping this mapping would silently
    // land anyone parked on the old Claude Code page in General.
    ["claude-code", "harness"],
    ["not-a-category", null],
  ])("resolves %s to %s", (value, expected) => {
    expect(resolveSettingsCategory(value)).toBe(expected);
  });
});
