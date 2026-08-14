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
