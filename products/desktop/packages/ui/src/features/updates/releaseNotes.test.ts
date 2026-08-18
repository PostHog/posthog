import { describe, expect, it } from "vitest";
import {
  compareVersions,
  groupReleases,
  mergeReleaseNotes,
  parseReleaseNotes,
  releasesBetween,
} from "./releaseNotes";

describe("parseReleaseNotes", () => {
  it("keeps change bullets, strips prefix + attribution, splits fix vs rest", () => {
    const notes = [
      "## What's Changed",
      "* feat(canvas): right-click a canvas by @alice in https://github.com/PostHog/code/pull/1",
      "* fix(inbox): point link to docs by @bob in https://github.com/PostHog/code/pull/2",
      '* Add "PostHog Web" button by @carol in https://github.com/PostHog/code/pull/3',
      "* @newbie made their first contribution in https://example.com",
      "**Full Changelog**: https://github.com/PostHog/code/compare/v1...v2",
    ].join("\n");

    expect(parseReleaseNotes(notes)).toEqual({
      improved: ["Right-click a canvas", 'Add "PostHog Web" button'],
      fixed: ["Point link to docs"],
    });
  });
});

describe("mergeReleaseNotes", () => {
  it("merges across releases and dedupes", () => {
    const releases = [
      { name: "v2", version: "2", date: null, notes: "* fix: a\n* feat: b" },
      { name: "v1", version: "1", date: null, notes: "* fix: a\n* feat: c" },
    ];
    expect(mergeReleaseNotes(releases)).toEqual({
      improved: ["B", "C"],
      fixed: ["A"],
    });
  });
});

describe("groupReleases", () => {
  const now = Date.parse("2026-06-20T12:00:00Z");
  const mk = (name: string, date: string) => ({
    name,
    version: name.replace(/^v/, ""),
    date,
    notes: "",
  });

  it("buckets recent releases by day and older ones by week", () => {
    const groups = groupReleases(
      [
        mk("v0.55.14", "2026-06-20T12:00:00Z"),
        mk("v0.55.13", "2026-06-19T12:00:00Z"),
        mk("v0.55.12", "2026-06-19T09:00:00Z"),
        mk("v0.55.5", "2026-06-12T12:00:00Z"),
        mk("v0.55.4", "2026-06-10T12:00:00Z"),
      ],
      now,
      3,
    );

    expect(groups).toHaveLength(3);
    expect(groups[0].key.startsWith("day-")).toBe(true);
    expect(groups[0].releases).toHaveLength(1);
    expect(groups[0].isLatest).toBe(true);
    expect(groups[1].key.startsWith("day-")).toBe(true);
    expect(groups[1].releases).toHaveLength(2);
    expect(groups[2].key.startsWith("week-")).toBe(true);
    expect(groups[2].releases).toHaveLength(2);
  });

  it("marks the newest stable release as latest, skipping a prerelease", () => {
    const groups = groupReleases(
      [
        { ...mk("v0.56.0-beta.1", "2026-06-20T12:00:00Z"), isPrerelease: true },
        mk("v0.55.14", "2026-06-19T12:00:00Z"),
      ],
      now,
      3,
    );

    expect(groups).toHaveLength(2);
    expect(groups[0].releases[0].name).toBe("v0.56.0-beta.1");
    expect(groups[0].isLatest).toBe(false);
    expect(groups[1].isLatest).toBe(true);
  });

  it("falls back to the newest group when every release is a prerelease", () => {
    const groups = groupReleases(
      [
        { ...mk("v0.56.0-beta.2", "2026-06-20T12:00:00Z"), isPrerelease: true },
        { ...mk("v0.56.0-beta.1", "2026-06-19T12:00:00Z"), isPrerelease: true },
      ],
      now,
      3,
    );

    expect(groups[0].isLatest).toBe(true);
  });
});

describe("compareVersions", () => {
  it.each([
    { a: "0.60.249", b: "0.60.231", expected: 1 },
    { a: "0.60.231", b: "0.60.249", expected: -1 },
    { a: "0.60.249", b: "0.60.249", expected: 0 },
    { a: "0.61.0", b: "0.60.999", expected: 1 },
    { a: "1.0.0", b: "0.99.99", expected: 1 },
    { a: "0.60", b: "0.60.0", expected: 0 },
    { a: "0.61.0", b: "0.61.0-beta.1", expected: 1 },
    { a: "0.61.0-beta.1", b: "0.61.0-beta.2", expected: -1 },
  ])("compares $a vs $b", ({ a, b, expected }) => {
    expect(Math.sign(compareVersions(a, b))).toBe(expected);
  });
});

describe("releasesBetween", () => {
  const release = (version: string) => ({
    name: `v${version}`,
    version,
    notes: "",
    date: null,
  });
  const feed = [
    release("0.60.249"),
    release("0.60.240"),
    release("0.60.231"),
    release("0.60.220"),
  ];

  it("returns releases newer than current up to and including the target", () => {
    expect(releasesBetween(feed, "0.60.231", "0.60.249")).toEqual([
      release("0.60.249"),
      release("0.60.240"),
    ]);
  });

  it("returns nothing when already on the target", () => {
    expect(releasesBetween(feed, "0.60.249", "0.60.249")).toEqual([]);
  });

  it("falls back to just the target release without a current version", () => {
    expect(releasesBetween(feed, null, "0.60.240")).toEqual([
      release("0.60.240"),
    ]);
  });

  it("excludes releases beyond the pending update", () => {
    expect(releasesBetween(feed, "0.60.220", "0.60.240")).toEqual([
      release("0.60.240"),
      release("0.60.231"),
    ]);
  });
});
