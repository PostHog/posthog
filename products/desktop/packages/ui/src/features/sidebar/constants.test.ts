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
    const withoutLoops = CUSTOMIZABLE_NAV_ITEM_IDS.filter(
      (id) => id !== "loops",
    ).reverse();

    const ids = orderedNavItems(withoutLoops).map((item) => item.id);

    expect(ids.indexOf("loops")).toBe(ids.indexOf("inbox") + 1);
  });

  it("inserts a missing id with no present predecessor at the start", () => {
    const ids = orderedNavItems(["command-center", "loops"]).map(
      (item) => item.id,
    );

    expect(ids[0]).toBe("inbox");
  });

  it("puts stored ids first and appends the rest in default order", () => {
    const ids = orderedNavItems(["configure", "inbox"]).map((item) => item.id);

    expect(ids.slice(0, 2)).toEqual(["configure", "inbox"]);
    expect(ids.slice(2)).toEqual(
      CUSTOMIZABLE_NAV_ITEM_IDS.filter(
        (id) => id !== "configure" && id !== "inbox",
      ),
    );
  });
});

describe("moveNavItem", () => {
  it("moves an item backward to the target position", () => {
    const next = moveNavItem([], "loops", "inbox");

    expect(next[0]).toBe("loops");
    expect(next).toHaveLength(CUSTOMIZABLE_NAV_ITEM_IDS.length);
  });

  it("moves an item forward to the target position", () => {
    const next = moveNavItem([], "inbox", "loops");

    expect(next.indexOf("inbox")).toBe(
      CUSTOMIZABLE_NAV_ITEM_IDS.indexOf("loops"),
    );
  });

  it.each([
    ["an unknown source", "retired-item", "inbox"],
    ["an unknown target", "inbox", "retired-item"],
    ["the same source and target", "inbox", "inbox"],
  ])("returns the order unchanged for %s", (_label, source, target) => {
    const order: readonly ("loops" | "inbox")[] = ["loops", "inbox"];

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
    ).toEqual(["loops", "inbox"]);
  });
});
