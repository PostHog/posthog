import { describe, expect, it } from "vitest";
import { spendMeterLayout } from "./SpendMeter";

describe("spendMeterLayout", () => {
  it("returns null when no line is set", () => {
    expect(spendMeterLayout(null, null, 12)).toBeNull();
  });

  it("scales to the highest of the lines and the spend, with headroom", () => {
    const layout = spendMeterLayout(20, 50, 7);
    expect(layout).not.toBeNull();
    expect(layout?.tone).toBe("ok");
    expect(layout?.alertPercent).toBeCloseTo((50 / 56) * 100, 5);
    expect(layout?.warnPercent).toBeCloseTo((20 / 56) * 100, 5);
    expect(layout?.fillPercent).toBeCloseTo((7 / 56) * 100, 5);
  });

  it("keeps a spend far past the alert line on the track", () => {
    const layout = spendMeterLayout(20, 50, 500);
    expect(layout?.tone).toBe("alert");
    expect(layout?.fillPercent).toBeLessThanOrEqual(100);
    expect(layout?.alertPercent).toBeLessThan(15);
  });

  it.each([
    [19.99, "ok"],
    [20, "warn"],
    [50, "alert"],
  ] as const)("spend %s -> tone %s", (spent, tone) => {
    expect(spendMeterLayout(20, 50, spent)?.tone).toBe(tone);
  });

  it("works with only one line set", () => {
    const layout = spendMeterLayout(null, 50, 60);
    expect(layout?.warnPercent).toBeNull();
    expect(layout?.tone).toBe("alert");
  });
});
