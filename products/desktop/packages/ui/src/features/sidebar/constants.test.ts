import { describe, expect, it } from "vitest";
import {
  CUSTOMIZABLE_NAV_ITEM_IDS,
  moveNavItem,
  orderedNavItems,
  sanitizeNavItemOrder,
} from "./constants";

describe("CUSTOMIZABLE_NAV_ITEM_IDS", () => {
  it("keeps configuration destinations out of the top-level navigation", () => {
    expect(CUSTOMIZABLE_NAV_ITEM_IDS).not.toEqual(
      expect.arrayContaining(["agents", "skills", "mcp-servers"]),
    );
  });

  it("keeps fixed search out of the customizable navigation", () => {
    expect(CUSTOMIZABLE_NAV_ITEM_IDS).not.toContain("search");
  });
});

describe("orderedNavItems", () => {
  it("returns the default order for an empty stored order", () => {
    expect(orderedNavItems([]).map((item) => item.id)).toEqual(
      CUSTOMIZABLE_NAV_ITEM_IDS,
    );
  });

  it("inserts an id missing from a full stored order after its default predecessor", () => {
    const withoutConfigure = CUSTOMIZABLE_NAV_ITEM_IDS.filter(
      (id) => id !== "configure",
    ).reverse();

    const ids = orderedNavItems(withoutConfigure).map((item) => item.id);

    expect(ids.indexOf("configure")).toBe(ids.indexOf("command-center") + 1);
  });

  it("inserts a missing id with no present predecessor at the start", () => {
    const ids = orderedNavItems(["command-center", "loops"]).map(
      (item) => item.id,
    );

    expect(ids[0]).toBe("activity");
  });

  it("puts stored ids first and appends the rest in default order", () => {
    const ids = orderedNavItems(["configure", "activity"]).map(
      (item) => item.id,
    );

    expect(ids.slice(0, 2)).toEqual(["configure", "activity"]);
    expect(ids.slice(2)).toEqual(
      CUSTOMIZABLE_NAV_ITEM_IDS.filter(
        (id) => id !== "configure" && id !== "activity",
      ),
    );
  });
});

describe("moveNavItem", () => {
  it("moves an item backward to the target position", () => {
    const next = moveNavItem([], "loops", "activity");

    expect(next[0]).toBe("loops");
    expect(next).toHaveLength(CUSTOMIZABLE_NAV_ITEM_IDS.length);
  });

  it("moves an item forward to the target position", () => {
    const next = moveNavItem([], "activity", "loops");

    expect(next.indexOf("activity")).toBe(
      CUSTOMIZABLE_NAV_ITEM_IDS.indexOf("loops"),
    );
  });

  it.each([
    ["an unknown source", "retired-item", "activity"],
    ["an unknown target", "activity", "retired-item"],
    ["the same source and target", "activity", "activity"],
  ])("returns the order unchanged for %s", (_label, source, target) => {
    const order = ["loops", "activity"] as const;

    expect(moveNavItem(order, source, target)).toBe(order);
  });
});

describe("sanitizeNavItemOrder", () => {
  it.each([
    ["a string", "corrupt"],
    ["an object", { inbox: 0 }],
    ["null", null],
    ["a number", 7],
  ])("returns an empty order when the value is %s", (_label, value) => {
    expect(sanitizeNavItemOrder(value)).toEqual([]);
  });

  it("drops unknown ids, non-strings and duplicates", () => {
    expect(
      sanitizeNavItemOrder(["loops", "retired-item", 7, "inbox", "loops"]),
    ).toEqual(["loops"]);
  });
});
