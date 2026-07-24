import { Stack, Wrench } from "@phosphor-icons/react";
import {
  formatTokens,
  formatUsd,
} from "@posthog/core/billing/spendAnalysisFormat";
import type {
  SpendAnalysisProductRow,
  SpendAnalysisToolRow,
} from "@posthog/core/billing/spendAnalysisTypes";
import { Table, Text } from "@radix-ui/themes";
import { UsageCard } from "./UsageCard";

function BreakdownTable({
  headers,
  widths,
  children,
}: {
  headers: string[];
  widths: string[];
  children: React.ReactNode;
}) {
  return (
    <Table.Root
      size="1"
      className="[&_td]:!py-1.5 [&_th]:!py-1.5 [&_table]:w-full [&_table]:table-fixed [&_td]:overflow-hidden [&_td]:align-middle [&_th]:align-middle"
    >
      <Table.Header>
        <Table.Row>
          {headers.map((h, i) => (
            <Table.ColumnHeaderCell
              key={h}
              className="font-normal text-[12px] text-gray-11"
              style={{ width: widths[i] }}
            >
              {h}
            </Table.ColumnHeaderCell>
          ))}
        </Table.Row>
      </Table.Header>
      <Table.Body>{children}</Table.Body>
    </Table.Root>
  );
}

export function ToolBreakdownCard({ rows }: { rows: SpendAnalysisToolRow[] }) {
  if (rows.length === 0) return null;
  return (
    <UsageCard
      icon={<Wrench size={14} className="text-(--gray-9)" />}
      title="By tool"
    >
      <BreakdownTable
        headers={["Tool", "Generations", "Avg input", "Cost"]}
        widths={["40%", "20%", "20%", "20%"]}
      >
        {rows.slice(0, 10).map((r) => (
          <Table.Row key={r.tool ?? "(null)"}>
            <Table.Cell>{r.tool ?? "Text response"}</Table.Cell>
            <Table.Cell>{r.generation_count.toLocaleString()}</Table.Cell>
            <Table.Cell>{formatTokens(r.avg_input_tokens)}</Table.Cell>
            <Table.Cell>{formatUsd(r.cost_usd)}</Table.Cell>
          </Table.Row>
        ))}
      </BreakdownTable>
    </UsageCard>
  );
}

export function ProductBreakdownCard({
  rows,
}: {
  rows: SpendAnalysisProductRow[];
}) {
  if (rows.length === 0) return null;
  return (
    <UsageCard
      icon={<Stack size={14} className="text-(--gray-9)" />}
      title="By product"
    >
      <BreakdownTable
        headers={["Product", "Events", "Cost"]}
        widths={["50%", "25%", "25%"]}
      >
        {rows.map((r) => (
          <Table.Row key={r.product ?? "(null)"}>
            <Table.Cell>
              <Text className="truncate">{r.product ?? "(none)"}</Text>
            </Table.Cell>
            <Table.Cell>{r.event_count.toLocaleString()}</Table.Cell>
            <Table.Cell>{formatUsd(r.cost_usd)}</Table.Cell>
          </Table.Row>
        ))}
      </BreakdownTable>
    </UsageCard>
  );
}
