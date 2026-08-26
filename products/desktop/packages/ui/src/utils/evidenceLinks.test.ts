import { describe, expect, it } from "vitest";
import { evidenceWebPath, parseEvidenceLink } from "./evidenceLinks";

describe("evidenceLinks", () => {
  it.each([
    ["evidence:insight/9pQx3", { kind: "insight", id: "9pQx3" }],
    ["evidence:error/018f-44aa", { kind: "error", id: "018f-44aa" }],
    ["evidence:custom-kind/abc_123", { kind: "custom-kind", id: "abc_123" }],
    ["evidence:flag/my%2Fflag", { kind: "flag", id: "my/flag" }],
  ])("parses %s", (href, expected) => {
    expect(parseEvidenceLink(href)).toEqual(expected);
  });

  it("ignores query params so links from older transcripts still resolve", () => {
    expect(
      parseEvidenceLink(
        "evidence:insight/9pQx3?value=28.1%25&desc=down&series=1,2&url=https%3A%2F%2Fexample.com",
      ),
    ).toEqual({ kind: "insight", id: "9pQx3" });
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

  it.each([
    ["insight", "9pQx3", "/insights/9pQx3"],
    ["dashboard", "12", "/dashboard/12"],
    ["error", "018f-44aa", "/error_tracking/018f-44aa"],
    ["replay", "s_01HQ4K", "/replay/s_01HQ4K"],
    ["flag", "42", "/feature_flags/42"],
    ["experiment", "7", "/experiments/7"],
    ["survey", "srv-11", "/surveys/srv-11"],
    ["ticket", "conv_88", "/support/tickets/conv_88"],
    ["trace", "t_9f2ab4", "/ai-observability/traces/t_9f2ab4"],
    ["eval", "ev_faith", "/ai-evals/evaluations/ev_faith"],
    ["cohort", "31", "/cohorts/31"],
    ["action", "5", "/data-management/actions/5"],
    ["person", "0192-aaaa", "/persons/0192-aaaa"],
    ["hogql", "SELECT 1", "/sql?open_query=SELECT%201"],
    // Flag pages only resolve by numeric id, so a key gets no direct URL.
    ["flag", "my-flag-key", null],
    // Kinds without a canonical object page.
    ["event", "cart_saved", null],
    ["something-new", "x1", null],
  ])("maps %s/%s to %s", (kind, id, expected) => {
    expect(evidenceWebPath(kind, id)).toBe(expected);
  });

  it("URL-encodes the id in the web path", () => {
    expect(evidenceWebPath("insight", "a/b c")).toBe("/insights/a%2Fb%20c");
  });
});
