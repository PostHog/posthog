import { type ReactElement, type ReactNode, useMemo } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'

import {
    type InsightActorsData,
    type RetentionActorRow,
    retentionPeriodColumns,
    summarizeRetentionIntervals,
    toRetentionActorRows,
} from './insightActorsTransforms'

// Renders the retention persons table — one row per cohort member, one column per return interval,
// each cell marking whether the person returned. Column headers carry the per-interval retained count
// and percentage (relative to the cohort), mirroring the app's retention persons modal.
export function RetentionActorsView({ data }: { data: InsightActorsData }): ReactElement {
    const periodCols = useMemo(() => retentionPeriodColumns(data), [data])
    const rows = useMemo(() => toRetentionActorRows(data, periodCols), [data, periodCols])
    const summary = useMemo(() => summarizeRetentionIntervals(rows, periodCols), [rows, periodCols])

    const columns = useMemo((): DataTableColumn<RetentionActorRow>[] => {
        const cols: DataTableColumn<RetentionActorRow>[] = [
            {
                key: 'actor',
                header: 'Person',
                render: (row): ReactNode => {
                    const displayName = row.email || row.name || row.distinct_id || 'Anonymous'
                    return (
                        <div className="flex flex-col">
                            <span className="font-medium">{displayName}</span>
                            {row.distinct_id && row.distinct_id !== displayName && (
                                <span className="text-xs text-muted-foreground">{row.distinct_id}</span>
                            )}
                        </div>
                    )
                },
            },
        ]

        summary.forEach((col, i) => {
            cols.push({
                key: `interval_${col.interval}`,
                align: 'center',
                header: (
                    <div className="flex flex-col items-center leading-tight">
                        <span>{col.label}</span>
                        <span className="text-xs font-normal text-muted-foreground">
                            {col.count} ({col.percentage}%)
                        </span>
                    </div>
                ),
                render: (row): ReactNode => {
                    const returned = row.appearances[i]
                    return (
                        <div
                            className={`mx-auto h-4 w-4 rounded-sm bg-[#1d4aff] ${returned ? '' : 'opacity-20'}`}
                            title={returned ? 'Returned' : 'Did not return'}
                        />
                    )
                },
            })
        })

        return cols
    }, [summary])

    return (
        <div className="p-4">
            <div className="flex flex-col gap-2">
                <span className="text-sm text-muted-foreground">
                    {rows.length} person{rows.length === 1 ? '' : 's'}
                    {data.hasMore ? '+' : ''} in this cohort
                </span>
                <DataTable<RetentionActorRow>
                    columns={columns}
                    data={rows}
                    emptyMessage="No persons found for this cohort"
                />
            </div>
        </div>
    )
}
