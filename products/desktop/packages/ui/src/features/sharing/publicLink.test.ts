import { describe, expect, it } from "vitest";
import { publicLinkHasUnpublishedChanges } from "./publicLink";

describe("publicLinkHasUnpublishedChanges", () => {
  it.each([
    ["no canvas record yet", undefined, false],
    [
      "not shared publicly",
      { publishedBuildId: "b2", sharedBuildId: null },
      false,
    ],
    [
      "shared and current",
      { publishedBuildId: "b1", sharedBuildId: "b1" },
      false,
    ],
    [
      "shared and a newer build is published",
      { publishedBuildId: "b2", sharedBuildId: "b1" },
      true,
    ],
    [
      "shared build gone and nothing published",
      { publishedBuildId: null, sharedBuildId: "b1" },
      false,
    ],
  ])("is %s", (_name, dashboard, expected) => {
    expect(publicLinkHasUnpublishedChanges(dashboard)).toBe(expected);
  });
});
