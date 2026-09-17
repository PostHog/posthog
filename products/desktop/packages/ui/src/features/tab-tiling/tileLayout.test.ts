import { describe, expect, it } from "vitest";
import {
  groupForTab,
  MAX_TILES_PER_GROUP,
  pruneGroups,
  setSplitSizes,
  type TileEdge,
  type TileGroup,
  type TileNode,
  tabIdsIn,
  tileTab,
  untileTab,
} from "./tileLayout";

/** Deterministic ids so trees can be compared with `toEqual`. */
function ids(): () => string {
  let n = 0;
  return () => `s${++n}`;
}

function leaf(tabId: string): TileNode {
  return { type: "tab", tabId };
}

function split(
  id: string,
  direction: "horizontal" | "vertical",
  children: TileNode[],
): TileNode {
  return { type: "split", id, direction, children };
}

/** Tile `tabId` next to the previously tiled tab, starting from `a`. */
function build(steps: [string, string, TileEdge][]): TileGroup[] {
  const makeId = ids();
  return steps.reduce<TileGroup[]>(
    (groups, [tabId, target, edge]) =>
      tileTab(groups, tabId, target, edge, makeId),
    [],
  );
}

describe("tileLayout", () => {
  it.each<{ edge: TileEdge; expected: TileNode }>([
    {
      edge: "right",
      expected: split("s1", "horizontal", [leaf("a"), leaf("b")]),
    },
    {
      edge: "left",
      expected: split("s1", "horizontal", [leaf("b"), leaf("a")]),
    },
    {
      edge: "bottom",
      expected: split("s1", "vertical", [leaf("a"), leaf("b")]),
    },
    { edge: "top", expected: split("s1", "vertical", [leaf("b"), leaf("a")]) },
  ])(
    "dropping on the $edge edge creates a split in that order",
    ({ edge, expected }) => {
      const groups = build([["b", "a", edge]]);
      expect(groups).toEqual([{ id: "s1", root: expected }]);
    },
  );

  it("keeps three tabs on one axis as one flat split", () => {
    const groups = build([
      ["b", "a", "right"],
      ["c", "b", "right"],
    ]);
    expect(groups[0].root).toEqual(
      split("s1", "horizontal", [leaf("a"), leaf("b"), leaf("c")]),
    );
  });

  it("nests a split on the other axis to form a grid", () => {
    const groups = build([
      ["b", "a", "right"],
      ["c", "a", "bottom"],
      ["d", "b", "bottom"],
    ]);
    expect(groups[0].root).toEqual(
      split("s1", "horizontal", [
        split("s2", "vertical", [leaf("a"), leaf("c")]),
        split("s3", "vertical", [leaf("b"), leaf("d")]),
      ]),
    );
  });

  it("moves a tiled tab into another group when dropped there", () => {
    const groups = build([
      ["b", "a", "right"],
      ["d", "c", "right"],
      ["b", "d", "bottom"],
    ]);
    expect(groupForTab(groups, "a")).toBeNull();
    expect(groups).toEqual([
      {
        id: "s2",
        root: split("s2", "horizontal", [
          leaf("c"),
          split("s3", "vertical", [leaf("d"), leaf("b")]),
        ]),
      },
    ]);
  });

  it("refuses a drop when the target group is full", () => {
    const steps: [string, string, TileEdge][] = [];
    for (let i = 1; i < MAX_TILES_PER_GROUP; i++) {
      steps.push([`t${i}`, "a", "right"]);
    }
    const full = build(steps);
    const after = tileTab(full, "extra", "a", "bottom", ids());
    expect(tabIdsIn(after[0].root)).toEqual(tabIdsIn(full[0].root));
    expect(groupForTab(after, "extra")).toBeNull();
  });

  it("ignores a drop of a tab onto its own tile", () => {
    const groups = build([["b", "a", "right"]]);
    expect(tileTab(groups, "a", "a", "left", ids())).toEqual(groups);
  });

  it("collapses the parent split when a tile leaves a grid", () => {
    const groups = build([
      ["b", "a", "right"],
      ["c", "a", "bottom"],
    ]);
    expect(untileTab(groups, "c")[0].root).toEqual(
      split("s1", "horizontal", [leaf("a"), leaf("b")]),
    );
  });

  it("dissolves the group when only one tile remains", () => {
    const groups = build([["b", "a", "right"]]);
    expect(untileTab(groups, "b")).toEqual([]);
  });

  it("records sizes and returns the same array for an unchanged layout", () => {
    const groups = build([["b", "a", "right"]]);
    const sized = setSplitSizes(groups, "s1", [30, 70]);
    expect(sized[0].root).toMatchObject({ sizes: [30, 70] });
    expect(setSplitSizes(sized, "s1", [30, 70])).toBe(sized);
  });

  it("prunes closed tabs and keeps the array when nothing closed", () => {
    const groups = build([
      ["b", "a", "right"],
      ["c", "a", "bottom"],
    ]);
    expect(pruneGroups(groups, ["a", "b", "c"])).toBe(groups);
    expect(pruneGroups(groups, ["a", "b"])[0].root).toEqual(
      split("s1", "horizontal", [leaf("a"), leaf("b")]),
    );
    expect(pruneGroups(groups, ["c"])).toEqual([]);
  });
});
