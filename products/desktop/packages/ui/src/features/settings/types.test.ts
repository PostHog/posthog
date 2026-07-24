import { describe, expect, it } from "vitest";
import { isSettingsCategory } from "./types";

describe("isSettingsCategory", () => {
  it("recognizes sidebar experience settings", () => {
    expect(isSettingsCategory("sidebar")).toBe(true);
  });
});
