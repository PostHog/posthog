import type { ReactElement } from 'react'

import { Badge, Card, DataTable, type DataTableColumn, ProgressBar, Stack } from '@posthog/mosaic'

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
            render: (row) =>
                row.probability != null ? (
                    <div className="flex items-center gap-2 justify-end">
                        <ProgressBar
                            value={row.probability * 100}
                            variant={row.probability > 0.95 ? 'success' : row.probability > 0.5 ? 'info' : 'warning'}
                            size="sm"
                            className="w-16"
                        />
                        <span className="tabular-nums">{(row.probability * 100).toFixed(1)}%</span>
                    </div>
                ) : (
                    '\u2014'
                ),
        },
        {
            key: 'significant',
            header: 'Significant',
            render: (row) =>
                row.significant != null ? (
                    <Badge variant={row.significant ? 'success' : 'neutral'} size="sm">
                        {row.significant ? 'Yes' : 'No'}
                    </Badge>
                ) : (
                    '\u2014'
                ),
        },
    ]

    return (
        <div className="p-4">
            <Stack gap="md">
                {data.experiment?.name && (
                    <span className="text-lg font-semibold text-text-primary">{data.experiment.name}</span>
                )}

                {exposureEntries.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Exposures</span>
                            <DataTable<ExperimentExposure>
                                columns={exposureColumns}
                                data={exposureEntries}
                                emptyMessage="No exposure data"
                            />
                        </Stack>
                    </Card>
                )}

                {allPrimary.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Primary metrics</span>
                            <DataTable<MetricResult>
                                columns={metricColumns}
                                data={allPrimary}
                                emptyMessage="No primary metric results"
                            />
                        </Stack>
                    </Card>
                )}

                {allSecondary.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Secondary metrics</span>
                            <DataTable<MetricResult>
                                columns={metricColumns}
                                data={allSecondary}
                                emptyMessage="No secondary metric results"
                            />
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
