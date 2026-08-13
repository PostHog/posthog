import { describe, expect, it } from "vitest";
import { searchSettings } from "./settingsSearch";
import type { SettingsCategory } from "./types";

const NO_HIDDEN: ReadonlySet<SettingsCategory> = new Set();

describe("searchSettings", () => {
  it.each([
    ["matches labels case-insensitively", "THEME", "Theme"],
    [
      "matches keywords the label doesn't contain",
      "elevenlabs",
      "Spoken narration",
    ],
    ["ranks a label prefix above keyword hits", "dock badge", "Dock badge"],
  ])("%s", (_name, query, expectedFirstLabel) => {
    const results = searchSettings(query, NO_HIDDEN);
    expect(results[0]?.label).toBe(expectedFirstLabel);
  });

  it("requires every token to match", () => {
    expect(searchSettings("dock zzzz", NO_HIDDEN)).toEqual([]);
  });

  it("excludes entries from hidden categories", () => {
    const hidden: ReadonlySet<SettingsCategory> = new Set(["terminal"]);
    const results = searchSettings("terminal", hidden);
    expect(results.every((r) => r.category !== "terminal")).toBe(true);
  });
});
