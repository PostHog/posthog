import type { ReactElement } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

export interface LLMCostSeries {
    label: string
    count: number
    data: number[]
    labels: string[]
    days: string[]
    aggregated_value: number
    breakdown_value?: string
}

export interface LLMCostsData {
    results: LLMCostSeries[]
    _posthogUrl?: string
}

export interface LLMCostsViewProps {
    data: LLMCostsData
}

function formatCurrency(value: number): string {
    return `$${value.toFixed(2)}`
}

interface ModelRow {
    model: string
    totalCost: number
    latestDayCost: number
}

export function LLMCostsView({ data }: LLMCostsViewProps): ReactElement {
    const series = data.results

    if (series.length === 0) {
        return (
            <div className="p-4">
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>No LLM cost data</EmptyTitle>
                        <EmptyDescription>No AI generation events found for this period</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    const totalCost = series.reduce((sum, s) => sum + (s.aggregated_value ?? 0), 0)

    const rows: ModelRow[] = series.map((s) => ({
        model: s.breakdown_value || s.label || 'Unknown',
        totalCost: s.aggregated_value ?? 0,
        latestDayCost: s.data?.length ? s.data[s.data.length - 1]! : 0,
    }))

    const columns: DataTableColumn<ModelRow>[] = [
        { key: 'model', header: 'Model', sortable: true },
        {
            key: 'totalCost',
            header: 'Total cost',
            align: 'right',
            sortable: true,
            render: (row) => <span className="tabular-nums">{formatCurrency(row.totalCost)}</span>,
        },
        {
            key: 'latestDayCost',
            header: 'Latest day',
            align: 'right',
            sortable: true,
            render: (row) => (
                <span className="tabular-nums text-muted-foreground">{formatCurrency(row.latestDayCost)}</span>
            ),
        },
    ]

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <span className="text-lg font-semibold">LLM costs</span>
                    <span className="text-2xl font-bold tabular-nums">{formatCurrency(totalCost)}</span>
                    <span className="text-xs text-muted-foreground">Total across all models</span>
                </div>

                <Card>
                    <CardContent>
                        <div className="flex flex-col gap-2">
                            <span className="text-sm font-semibold">Breakdown by model</span>
                            <DataTable<ModelRow>
                                columns={columns}
                                data={rows}
                                defaultSort={{ key: 'totalCost', direction: 'desc' }}
                                emptyMessage="No model data"
                            />
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
