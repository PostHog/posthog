import type { ReactElement } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Card, CardContent, cn } from '@posthog/quill'

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

function RateBar({ value, fillClass }: { value: number; fillClass: string }): ReactElement {
    const pct = Math.max(0, Math.min(100, value))
    return (
        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div className={cn('h-full transition-all', fillClass)} style={{ width: `${pct}%` }} />
        </div>
    )
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
            <div className="flex flex-col gap-3">
                <span className="text-lg font-semibold">Survey stats</span>

                {data.rates && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                {data.rates.response_rate != null && (
                                    <div>
                                        <div className="flex justify-between text-sm mb-1">
                                            <span className="text-muted-foreground">Response rate</span>
                                            <span className="tabular-nums">
                                                {(data.rates.response_rate * 100).toFixed(1)}%
                                            </span>
                                        </div>
                                        <RateBar value={data.rates.response_rate * 100} fillClass="bg-emerald-500" />
                                    </div>
                                )}
                                {data.rates.dismissal_rate != null && (
                                    <div>
                                        <div className="flex justify-between text-sm mb-1">
                                            <span className="text-muted-foreground">Dismissal rate</span>
                                            <span className="tabular-nums">
                                                {(data.rates.dismissal_rate * 100).toFixed(1)}%
                                            </span>
                                        </div>
                                        <RateBar value={data.rates.dismissal_rate * 100} fillClass="bg-amber-500" />
                                    </div>
                                )}
                            </div>
                        </CardContent>
                    </Card>
                )}

                {entries.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">Events</span>
                                <DataTable<SurveyStatEntry>
                                    columns={columns}
                                    data={entries}
                                    emptyMessage="No stats available"
                                />
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
