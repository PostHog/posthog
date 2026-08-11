import { Robot } from "@phosphor-icons/react";
import {
  formatTokens,
  formatUsd,
} from "@posthog/core/billing/spendAnalysisFormat";
import type { SpendAnalysisModelRow } from "@posthog/core/billing/spendAnalysisTypes";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Text,
} from "@posthog/quill";
import type { ReactElement } from "react";
import { useState } from "react";
import { UsageCard } from "./UsageCard";

export type ModelBreakdownSort = "cost" | "tokens";

export function sortModelBreakdownRows(
  rows: SpendAnalysisModelRow[],
  sortBy: ModelBreakdownSort,
): SpendAnalysisModelRow[] {
  return [...rows].sort((first, second) => {
    const firstValue =
      sortBy === "cost"
        ? first.cost_usd
        : first.input_tokens + first.output_tokens;
    const secondValue =
      sortBy === "cost"
        ? second.cost_usd
        : second.input_tokens + second.output_tokens;

    if (firstValue !== secondValue) return secondValue - firstValue;
    if (first.cost_usd !== second.cost_usd)
      return second.cost_usd - first.cost_usd;

    return (first.model ?? "").localeCompare(second.model ?? "");
  });
}

function ModelStat({
  label,
  value,
}: {
  label: string;
  value: string;
}): ReactElement {
  return (
    <div className="flex items-center justify-between">
      <Text size="xs" variant="muted">
        {label}
      </Text>
      <Text size="xs">{value}</Text>
    </div>
  );
}

interface ModelBreakdownCardsProps {
  rows: SpendAnalysisModelRow[];
  scopedCostUsd: number;
}

export function ModelBreakdownCards({
  rows,
  scopedCostUsd,
}: ModelBreakdownCardsProps): ReactElement | null {
  const [sortBy, setSortBy] = useState<ModelBreakdownSort>("cost");

  if (rows.length === 0) return null;

  const sortedRows = sortModelBreakdownRows(rows, sortBy);

  return (
    <UsageCard
      icon={<Robot size={14} className="text-(--gray-9)" />}
      title="Cost by model"
      actions={
        <div className="flex items-center gap-2">
          <Text size="xs" variant="muted">
            Sort by
          </Text>
          <Select
            value={sortBy}
            onValueChange={(value: ModelBreakdownSort | null) => {
              if (value) setSortBy(value);
            }}
          >
            <SelectTrigger size="sm" aria-label="Sort models">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" side="bottom" sideOffset={6}>
              <SelectItem value="cost">Cost</SelectItem>
              <SelectItem value="tokens">Total tokens</SelectItem>
            </SelectContent>
          </Select>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sortedRows.map((row) => {
          const share =
            scopedCostUsd > 0
              ? Math.round((row.cost_usd / scopedCostUsd) * 100)
              : 0;
          return (
            <div
              key={row.model ?? "(unknown)"}
              className="flex flex-col gap-2 rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2) p-3"
            >
              <div className="flex items-center gap-2">
                <Text size="sm" weight="medium" className="truncate">
                  {row.model ?? "(unknown)"}
                </Text>
                <div className="flex-1" />
                <Text
                  size="sm"
                  weight="semibold"
                  className="text-(--accent-11)"
                >
                  {formatUsd(row.cost_usd)}
                </Text>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="col-span-2">
                  <ModelStat
                    label="Total tokens"
                    value={formatTokens(row.input_tokens + row.output_tokens)}
                  />
                </div>
                <ModelStat
                  label="Input"
                  value={formatTokens(row.input_tokens)}
                />
                <ModelStat
                  label="Output"
                  value={formatTokens(row.output_tokens)}
                />
                <ModelStat
                  label="Generations"
                  value={row.generation_count.toLocaleString()}
                />
                <ModelStat label="Share" value={`${share}%`} />
              </div>
            </div>
          );
        })}
      </div>
    </UsageCard>
  );
}
