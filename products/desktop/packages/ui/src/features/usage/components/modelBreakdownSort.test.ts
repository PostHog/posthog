import type { SpendAnalysisModelRow } from "@posthog/core/billing/spendAnalysisTypes";
import { describe, expect, it } from "vitest";
import { sortModelBreakdownRows } from "./ModelBreakdownCards";

describe("sortModelBreakdownRows", () => {
  const rows: SpendAnalysisModelRow[] = [
    {
      model: "highest-cost",
      cost_usd: 10,
      input_tokens: 100,
      output_tokens: 50,
      generation_count: 1,
    },
    {
      model: "most-tokens",
      cost_usd: 2,
      input_tokens: 900,
      output_tokens: 100,
      generation_count: 1,
    },
  ];

  it("orders models by the selected metric without changing the input rows", () => {
    expect(
      sortModelBreakdownRows(rows, "cost").map((row) => row.model),
    ).toEqual(["highest-cost", "most-tokens"]);
    expect(
      sortModelBreakdownRows(rows, "tokens").map((row) => row.model),
    ).toEqual(["most-tokens", "highest-cost"]);
    expect(rows.map((row) => row.model)).toEqual([
      "highest-cost",
      "most-tokens",
    ]);
  });
});
