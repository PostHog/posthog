import { describe, expect, it } from "vitest";
import { parseChartBlock } from "./chartBlocks";

describe("parseChartBlock", () => {
  it("parses an inline data block", () => {
    expect(
      parseChartBlock(
        JSON.stringify({
          title: "Daily active users",
          render: "bar",
          labels: ["Aug 7", "Aug 8"],
          series: [{ name: "DAU", points: [69650, 39431] }],
        }),
      ),
    ).toEqual({
      mode: "data",
      title: "Daily active users",
      caption: undefined,
      render: "bar",
      labels: ["Aug 7", "Aug 8"],
      series: [{ name: "DAU", points: [69650, 39431] }],
    });
  });

  it("defaults render to line and names unnamed series", () => {
    const spec = parseChartBlock(
      JSON.stringify({ series: [{ points: [1, 2] }] }),
    );
    expect(spec).toMatchObject({
      mode: "data",
      render: "line",
      series: [{ name: "Series 1", points: [1, 2] }],
    });
  });

  it("routes a query payload to query mode without validating the node", () => {
    const query = { kind: "InsightVizNode", source: { kind: "TrendsQuery" } };
    expect(parseChartBlock(JSON.stringify({ title: "T", query }))).toEqual({
      mode: "query",
      title: "T",
      caption: undefined,
      query,
    });
  });

  it.each([
    ["malformed JSON", "{not json"],
    ["no series or query", '{"title":"x"}'],
    ["only non-numeric points", '{"series":[{"points":["a","b"]}]}'],
    ["an array payload", "[1,2,3]"],
  ])("returns null for %s", (_name, source) => {
    expect(parseChartBlock(source)).toBeNull();
  });

  it("caps series count and points so a runaway block cannot flood the card", () => {
    const spec = parseChartBlock(
      JSON.stringify({
        series: Array.from({ length: 30 }, () => ({
          points: Array.from({ length: 500 }, (_, i) => i),
        })),
      }),
    );
    expect(spec?.mode).toBe("data");
    if (spec?.mode === "data") {
      expect(spec.series.length).toBe(15);
      expect(spec.series[0].points.length).toBe(366);
    }
  });
});
