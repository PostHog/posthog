import { useMemo } from 'react'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AggregatedSpanRow } from '~/queries/schema/schema-general'

import { formatDuration } from './TraceWaterfallView'
import { VirtualizedTable, VirtualizedTableColumn } from './VirtualizedTable'

// Span count over the aggregation window, rendered as a request rate. Empty window → no rate.
function formatRate(count: number, windowMs: number): string {
    const seconds = windowMs / 1000
    if (!seconds) {
        return '—'
    }
    const perSec = count / seconds
    if (perSec >= 1) {
        return `${humanFriendlyNumber(perSec, perSec >= 10 ? 0 : 1)}/s`
    }
    const perMin = perSec * 60
    if (perMin >= 1) {
        return `${humanFriendlyNumber(perMin, 1)}/min`
    }
    return `${humanFriendlyNumber(perSec * 3600, 1)}/hr`
}

function errorRate(row: AggregatedSpanRow): number {
    return row.count > 0 ? row.error_count / row.count : 0
}

const durationCell =
    (pick: (row: AggregatedSpanRow) => number) =>
    (row: AggregatedSpanRow): JSX.Element => <span className="font-mono">{formatDuration(pick(row))}</span>

function buildColumns(windowMs: number): VirtualizedTableColumn<AggregatedSpanRow>[] {
    return [
        {
            key: 'service_name',
            title: 'Service',
            width: 150,
            sorter: (a, b) => a.service_name.localeCompare(b.service_name),
            render: (row) => <span className="font-mono">{row.service_name}</span>,
        },
        {
            key: 'name',
            title: 'Operation',
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (row) => <span className="font-mono">{row.name}</span>,
        },
        {
            key: 'requests',
            title: 'Requests',
            width: 120,
            align: 'right',
            sorter: (a, b) => a.count - b.count,
            render: (row) => (
                <div className="flex flex-col items-end">
                    <span>{formatRate(row.count, windowMs)}</span>
                    <span className="text-xs text-muted">{humanFriendlyNumber(row.count)}</span>
                </div>
            ),
        },
        {
            key: 'error_rate',
            title: 'Error rate',
            width: 90,
            align: 'right',
            sorter: (a, b) => errorRate(a) - errorRate(b),
            render: (row) => {
                const rate = errorRate(row)
                return (
                    <span className={rate > 0 ? 'text-danger' : 'text-muted'}>
                        {`${(rate * 100).toFixed(rate > 0 && rate < 0.01 ? 2 : 1)}%`}
                    </span>
                )
            },
        },
        {
            key: 'errors',
            title: 'Errors',
            width: 80,
            align: 'right',
            sorter: (a, b) => a.error_count - b.error_count,
            render: (row) => (
                <span className={row.error_count > 0 ? 'text-danger' : 'text-muted'}>
                    {humanFriendlyNumber(row.error_count)}
                </span>
            ),
        },
        {
            key: 'p50',
            title: 'p50',
            width: 80,
            align: 'right',
            sorter: (a, b) => a.p50_duration_nano - b.p50_duration_nano,
            render: durationCell((row) => row.p50_duration_nano),
        },
        {
            key: 'p95',
            title: 'p95',
            width: 80,
            align: 'right',
            sorter: (a, b) => a.p95_duration_nano - b.p95_duration_nano,
            render: durationCell((row) => row.p95_duration_nano),
        },
        {
            key: 'p99',
            title: 'p99',
            width: 80,
            align: 'right',
            sorter: (a, b) => a.p99_duration_nano - b.p99_duration_nano,
            render: durationCell((row) => row.p99_duration_nano),
        },
        {
            key: 'p999',
            title: 'p99.9',
            width: 80,
            align: 'right',
            sorter: (a, b) => a.p999_duration_nano - b.p999_duration_nano,
            render: durationCell((row) => row.p999_duration_nano),
        },
        {
            key: 'total_time',
            title: 'Total time',
            width: 100,
            align: 'right',
            // Per the JON-89 spike: wall-time, not self-time — nesting is double-counted; labelled as such.
            tooltip: 'Sum of span wall-clock durations; nested spans are counted in both parent and child.',
            sorter: (a, b) => a.total_duration_nano - b.total_duration_nano,
            render: durationCell((row) => row.total_duration_nano),
        },
    ]
}

export interface OperationsTableProps {
    rows: AggregatedSpanRow[]
    loading: boolean
    /** Resolved aggregation window (ms) — turns span counts into a request rate. */
    windowMs: number
    onRowClick?: (row: AggregatedSpanRow) => void
}

export function OperationsTable({ rows, loading, windowMs, onRowClick }: OperationsTableProps): JSX.Element {
    const columns = useMemo(() => buildColumns(windowMs), [windowMs])
    return (
        <VirtualizedTable<AggregatedSpanRow>
            columns={columns}
            dataSource={rows}
            loading={loading}
            rowKey={(row) => `${row.service_name}::${row.name}`}
            onRowClick={onRowClick}
            defaultSort={{ columnKey: 'total_time', order: -1 }}
            emptyLabel="No operations found for these filters"
            data-attr="tracing-operations-table"
        />
    )
}
