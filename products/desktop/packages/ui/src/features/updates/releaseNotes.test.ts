import { describe, expect, it } from "vitest";
import {
  groupReleases,
  mergeReleaseNotes,
  parseReleaseNotes,
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
