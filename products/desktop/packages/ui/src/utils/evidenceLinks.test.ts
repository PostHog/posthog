import { describe, expect, it } from "vitest";
import { parseEvidenceLink } from "./evidenceLinks";

describe("parseEvidenceLink", () => {
  it.each([
    ["evidence:insight/9pQx3", { kind: "insight", id: "9pQx3" }],
    ["evidence:error/018f-44aa", { kind: "error", id: "018f-44aa" }],
    ["evidence:custom-kind/abc_123", { kind: "custom-kind", id: "abc_123" }],
    ["evidence:flag/my%2Fflag", { kind: "flag", id: "my/flag" }],
  ])("parses %s", (href, expected) => {
    expect(parseEvidenceLink(href)).toEqual(expected);
  });

  it("carries a PostHog web url from the query", () => {
    const url = "https://us.posthog.com/project/2/insights/9pQx3";
    expect(
      parseEvidenceLink(
        `evidence:insight/9pQx3?url=${encodeURIComponent(url)}`,
      ),
    ).toEqual({ kind: "insight", id: "9pQx3", url });
  });

  it("carries display params for the hover card", () => {
    expect(
      parseEvidenceLink(
        "evidence:insight/9pQx3?value=28.1%25&desc=down+12.9pts+since+Jan+3",
      ),
    ).toEqual({
      kind: "insight",
      id: "9pQx3",
      value: "28.1%",
      desc: "down 12.9pts since Jan 3",
    });
  });

  it("caps display params so a runaway link cannot flood the card", () => {
    const parsed = parseEvidenceLink(
      `evidence:insight/x?value=${"9".repeat(80)}&desc=${"a".repeat(400)}`,
    );
    expect(parsed?.value?.length).toBe(40);
    expect(parsed?.desc?.length).toBe(160);
  });

  it("parses a series param into sparkline points", () => {
    expect(
      parseEvidenceLink("evidence:insight/x?series=41,39.5,+40,28"),
    ).toEqual({
      kind: "insight",
      id: "x",
      series: [41, 39.5, 40, 28],
    });
  });

  it.each([
    ["a single point", "series=41"],
    ["junk among the numbers", "series=41,down,28"],
  ])("drops a series with %s instead of a broken sparkline", (_name, query) => {
    expect(parseEvidenceLink(`evidence:insight/x?${query}`)).toEqual({
      kind: "insight",
      id: "x",
    });
  });

  it("caps series points so a runaway link cannot flood the card", () => {
    const parsed = parseEvidenceLink(
      `evidence:insight/x?series=${Array.from({ length: 200 }, (_, i) => i).join(",")}`,
    );
    expect(parsed?.series?.length).toBe(60);
  });

  it("drops url values that are not http(s)", () => {
    expect(
      parseEvidenceLink(
        `evidence:insight/x?url=${encodeURIComponent("javascript:alert(1)")}`,
      ),
    ).toEqual({ kind: "insight", id: "x" });
  });

  it.each([
    [undefined],
    ["https://example.com/evidence:insight/x"],
    ["evidence:"],
    ["evidence:insight"],
    ["evidence:insight/"],
    ["evidence:/9pQx3"],
    ["evidence:Insight/9pQx3"],
    ["chart:9pQx3"],
  ])("returns null for %s", (href) => {
    expect(parseEvidenceLink(href)).toBeNull();
  });
});
