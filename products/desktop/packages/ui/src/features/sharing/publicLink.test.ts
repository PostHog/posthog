import { describe, expect, it } from "vitest";
import {
  fileLinkHasUnpublishedChanges,
  publicLinkHasUnpublishedChanges,
} from "./publicLink";

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

describe("fileLinkHasUnpublishedChanges", () => {
  it.each([
    ["no sharing state yet", undefined, false],
    [
      "not shared publicly",
      { enabled: false, sharedArtifactId: "u1", latestArtifactId: "u2" },
      false,
    ],
    [
      "shared and current",
      { enabled: true, sharedArtifactId: "u1", latestArtifactId: "u1" },
      false,
    ],
    [
      "shared and uploaded again since",
      { enabled: true, sharedArtifactId: "u1", latestArtifactId: "u2" },
      true,
    ],
  ])("is %s", (_name, sharing, expected) => {
    expect(fileLinkHasUnpublishedChanges(sharing)).toBe(expected);
  });
});
