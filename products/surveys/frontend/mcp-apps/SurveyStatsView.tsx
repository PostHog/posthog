import type { ReactElement } from 'react'

import { Card, DataTable, type DataTableColumn, ProgressBar, Stack } from '@posthog/mosaic'

export interface SurveyStatEntry {
    name: string
    total_count: number
    unique_persons: number
}

export interface SurveyStatsData {
    survey_id?: string
    stats?: Record<string, { total_count: number; unique_persons: number }>
    rates?: { response_rate?: number; dismissal_rate?: number }
    _posthogUrl?: string
}

export interface SurveyStatsViewProps {
    data: SurveyStatsData
}

export function SurveyStatsView({ data }: SurveyStatsViewProps): ReactElement {
    const entries: SurveyStatEntry[] = data.stats
        ? Object.entries(data.stats).map(([name, val]) => ({
              name,
              total_count: val.total_count,
              unique_persons: val.unique_persons,
          }))
        : []

    const columns: DataTableColumn<SurveyStatEntry>[] = [
        { key: 'name', header: 'Event', sortable: true },
        { key: 'total_count', header: 'Total', align: 'right', sortable: true },
        { key: 'unique_persons', header: 'Unique persons', align: 'right', sortable: true },
    ]

    return (
        <div className="p-4">
            <Stack gap="md">
                <span className="text-lg font-semibold text-text-primary">Survey stats</span>

                {data.rates && (
                    <Card padding="md">
                        <Stack gap="sm">
                            {data.rates.response_rate != null && (
                                <div>
                                    <div className="flex justify-between text-sm mb-1">
                                        <span className="text-text-secondary">Response rate</span>
                                        <span className="text-text-primary tabular-nums">
                                            {(data.rates.response_rate * 100).toFixed(1)}%
                                        </span>
                                    </div>
                                    <ProgressBar value={data.rates.response_rate * 100} variant="success" size="md" />
                                </div>
                            )}
                            {data.rates.dismissal_rate != null && (
                                <div>
                                    <div className="flex justify-between text-sm mb-1">
                                        <span className="text-text-secondary">Dismissal rate</span>
                                        <span className="text-text-primary tabular-nums">
                                            {(data.rates.dismissal_rate * 100).toFixed(1)}%
                                        </span>
                                    </div>
                                    <ProgressBar value={data.rates.dismissal_rate * 100} variant="warning" size="md" />
                                </div>
                            )}
                        </Stack>
                    </Card>
                )}

                {entries.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Events</span>
                            <DataTable<SurveyStatEntry>
                                columns={columns}
                                data={entries}
                                emptyMessage="No stats available"
                            />
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
