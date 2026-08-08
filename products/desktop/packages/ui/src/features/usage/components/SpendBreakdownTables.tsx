import { Stack, Wrench } from "@phosphor-icons/react";
import {
  formatTokens,
  formatUsd,
} from "@posthog/core/billing/spendAnalysisFormat";
import type {
  SpendAnalysisProductRow,
  SpendAnalysisToolRow,
} from "@posthog/core/billing/spendAnalysisTypes";
import { Table } from "@radix-ui/themes";
import { UsageCard } from "./UsageCard";

interface BreakdownColumn {
  label: string;
  width: string;
  numeric?: boolean;
}

function BreakdownTable({
  columns,
  children,
}: {
  columns: BreakdownColumn[];
  children: React.ReactNode;
}) {
  return (
    <Table.Root
      size="1"
      className="[&_td]:!py-1.5 [&_th]:!py-1.5 [&_table]:w-full [&_table]:table-fixed [&_td]:overflow-hidden [&_td]:align-middle [&_th]:align-middle"
    >
      <Table.Header>
        <Table.Row>
          {columns.map((column) => (
            <Table.ColumnHeaderCell
              key={column.label}
              className={`!text-gray-11 whitespace-nowrap font-normal text-[12px] ${column.numeric ? "text-right" : ""}`}
              style={{ width: column.width }}
            >
              {column.label}
            </Table.ColumnHeaderCell>
          ))}
        </Table.Row>
      </Table.Header>
      <Table.Body>{children}</Table.Body>
    </Table.Root>
  );
}

/** Long tool and product names truncate; the full value stays in the title. */
function NameCell({ value }: { value: string }) {
  return (
    <Table.Cell>
      <span className="block truncate" title={value}>
        {value}
      </span>
    </Table.Cell>
  );
}

function NumericCell({ value }: { value: string }) {
  return (
    <Table.Cell className="whitespace-nowrap text-right tabular-nums">
      {value}
    </Table.Cell>
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
        columns={[
          { label: "Tool", width: "44%" },
          { label: "Gens", width: "16%", numeric: true },
          { label: "Avg input", width: "20%", numeric: true },
          { label: "Cost", width: "20%", numeric: true },
        ]}
      >
        {rows.slice(0, 10).map((r) => (
          <Table.Row key={r.tool ?? "(null)"}>
            <NameCell value={r.tool ?? "Text response"} />
            <NumericCell value={r.generation_count.toLocaleString()} />
            <NumericCell value={formatTokens(r.avg_input_tokens)} />
            <NumericCell value={formatUsd(r.cost_usd)} />
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
        columns={[
          { label: "Product", width: "50%" },
          { label: "Events", width: "25%", numeric: true },
          { label: "Cost", width: "25%", numeric: true },
        ]}
      >
        {rows.map((r) => (
          <Table.Row key={r.product ?? "(null)"}>
            <NameCell value={r.product ?? "(none)"} />
            <NumericCell value={r.event_count.toLocaleString()} />
            <NumericCell value={formatUsd(r.cost_usd)} />
          </Table.Row>
        ))}
      </BreakdownTable>
    </UsageCard>
  );
}
