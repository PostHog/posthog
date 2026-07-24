import type { ReactElement } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Badge, Card, CardContent, Progress } from '@posthog/quill'

export interface ExperimentExposure {
    variant: string
    count: number
}

export interface MetricResult {
    name?: string
    variant: string
    count?: number
    exposure?: number
    absolute_exposure?: number
    probability?: number
    significant?: boolean
}

export interface ExperimentResultsData {
    experiment?: { id: number; name?: string }
    primaryMetricsResults?: MetricResult[][]
    secondaryMetricsResults?: MetricResult[][]
    exposures?: Record<string, number>
    _posthogUrl?: string
}

export interface ExperimentResultsViewProps {
    data: ExperimentResultsData
}

function ProbabilityBar({ value }: { value: number }): ReactElement {
    const pct = Math.max(0, Math.min(100, value * 100))
    const variant: 'success' | 'default' | 'warning' = value > 0.95 ? 'success' : value > 0.5 ? 'default' : 'warning'
    return (
        <div className="flex items-center gap-2 justify-end">
            <Progress value={pct} variant={variant} className="w-16" />
            <span className="tabular-nums">{pct.toFixed(1)}%</span>
        </div>
    )
}

export function ExperimentResultsView({ data }: ExperimentResultsViewProps): ReactElement {
    const exposureEntries = data.exposures
        ? Object.entries(data.exposures).map(([variant, count]) => ({ variant, count: count as number }))
        : []

    const exposureColumns: DataTableColumn<ExperimentExposure>[] = [
        { key: 'variant', header: 'Variant', sortable: true },
        { key: 'count', header: 'Exposures', align: 'right', sortable: true },
    ]

    const allPrimary = (data.primaryMetricsResults ?? []).flat()
    const allSecondary = (data.secondaryMetricsResults ?? []).flat()

    const metricColumns: DataTableColumn<MetricResult>[] = [
        { key: 'variant', header: 'Variant', sortable: true },
        { key: 'count', header: 'Count', align: 'right' },
        {
            key: 'probability',
            header: 'Probability',
            align: 'right',
            render: (row) => (row.probability != null ? <ProbabilityBar value={row.probability} /> : '\u2014'),
        },
        {
            key: 'significant',
            header: 'Significant',
            render: (row) =>
                row.significant != null ? (
                    <Badge variant={row.significant ? 'success' : 'default'}>{row.significant ? 'Yes' : 'No'}</Badge>
                ) : (
                    '\u2014'
                ),
        },
    ]

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                {data.experiment?.name && <span className="text-lg font-semibold">{data.experiment.name}</span>}

                {exposureEntries.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">Exposures</span>
                                <DataTable<ExperimentExposure>
                                    columns={exposureColumns}
                                    data={exposureEntries}
                                    emptyMessage="No exposure data"
                                />
                            </div>
                        </CardContent>
                    </Card>
                )}

                {allPrimary.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">Primary metrics</span>
                                <DataTable<MetricResult>
                                    columns={metricColumns}
                                    data={allPrimary}
                                    emptyMessage="No primary metric results"
                                />
                            </div>
                        </CardContent>
                    </Card>
                )}

                {allSecondary.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">Secondary metrics</span>
                                <DataTable<MetricResult>
                                    columns={metricColumns}
                                    data={allSecondary}
                                    emptyMessage="No secondary metric results"
                                />
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
