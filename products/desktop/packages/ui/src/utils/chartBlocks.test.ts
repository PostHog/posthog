import { describe, expect, it } from "vitest";
import { chartBlockKey, parseChartBlock } from "./chartBlocks";

describe("chartBlocks", () => {
  it("parses an insight reference", () => {
    expect(
      parseChartBlock('{"mode":"insight","shortId":"9pQx3","title":"DAU"}'),
    ).toEqual({
      mode: "insight",
      shortId: "9pQx3",
      title: "DAU",
      caption: undefined,
    });
  });

  it("parses a hogql query with title and caption", () => {
    expect(
      parseChartBlock(
        '{"mode":"hogql","query":"SELECT 1","title":"T","caption":"C"}',
      ),
    ).toEqual({ mode: "hogql", query: "SELECT 1", title: "T", caption: "C" });
  });

  it("caps a runaway title so it cannot flood the card", () => {
    const spec = parseChartBlock(
      `{"mode":"hogql","query":"SELECT 1","title":"${"x".repeat(400)}"}`,
    );
    expect(spec?.title?.length).toBe(120);
  });

  it("parses a replay reference", () => {
    expect(parseChartBlock('{"mode":"replay","sessionId":"s_01HQ4K"}')).toEqual(
      {
        mode: "replay",
        sessionId: "s_01HQ4K",
        title: undefined,
        caption: undefined,
      },
    );
  });

  it.each([
    ["malformed JSON", '{"mode":"hogql","query":'],
    ["unknown mode", '{"mode":"data","series":[]}'],
    ["insight without an id", '{"mode":"insight"}'],
    ["hogql without a query", '{"mode":"hogql","query":"  "}'],
    ["non-object payload", '"SELECT 1"'],
  ])("returns null for %s", (_name, source) => {
    expect(parseChartBlock(source)).toBeNull();
  });

  it("keys equal sources identically and different sources apart", () => {
    const a = '{"mode":"hogql","query":"SELECT 1"}';
    const b = '{"mode":"hogql","query":"SELECT 2"}';
    expect(chartBlockKey(a)).toBe(chartBlockKey(a));
    expect(chartBlockKey(a)).not.toBe(chartBlockKey(b));
  });
});
