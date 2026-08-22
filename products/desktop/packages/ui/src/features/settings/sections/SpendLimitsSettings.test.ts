import { describe, expect, it } from "vitest";
import { parseSpendLimitField } from "./SpendLimitsSettings";

describe("parseSpendLimitField", () => {
  it.each([
    ["", { ok: true, value: null }],
    ["   ", { ok: true, value: null }],
    ["20", { ok: true, value: 20 }],
    ["$20", { ok: true, value: 20 }],
    ["12.345", { ok: true, value: 12.35 }],
    ["0", { ok: false }],
    ["-5", { ok: false }],
    ["abc", { ok: false }],
  ] as const)("%j", (raw, expected) => {
    expect(parseSpendLimitField(raw)).toEqual(expected);
  });
});
