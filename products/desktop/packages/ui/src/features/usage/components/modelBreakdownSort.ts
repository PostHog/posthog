import type { SpendAnalysisModelRow } from "@posthog/core/billing/spendAnalysisTypes";

export type ModelBreakdownSort = "cost" | "tokens";

function tokenCount(row: SpendAnalysisModelRow): number {
  return row.input_tokens + row.output_tokens;
}

export function sortModelBreakdownRows(
  rows: SpendAnalysisModelRow[],
  sortBy: ModelBreakdownSort,
): SpendAnalysisModelRow[] {
  return [...rows].sort((first, second) => {
    const firstValue = sortBy === "cost" ? first.cost_usd : tokenCount(first);
    const secondValue =
      sortBy === "cost" ? second.cost_usd : tokenCount(second);

    if (firstValue !== secondValue) return secondValue - firstValue;
    if (first.cost_usd !== second.cost_usd)
      return second.cost_usd - first.cost_usd;

    return (first.model ?? "").localeCompare(second.model ?? "");
  });
}
