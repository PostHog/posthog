import { useMemo } from 'react'

import { LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { AggregatedSpanRow } from '@posthog/query-frontend/schema/schema-general'

import { humanFriendlyNumber } from 'lib/utils'

import { formatDuration } from './TraceWaterfallView'

interface CompareRow {
    service_name: string
    name: string
    current: AggregatedSpanRow | null
    previous: AggregatedSpanRow | null
}

const rowKey = (row: { service_name: string; name: string }): string => `${row.service_name}\u0000${row.name}`

function buildRows(current: AggregatedSpanRow[], previous: AggregatedSpanRow[] | null): CompareRow[] {
    const previousByKey = new Map<string, AggregatedSpanRow>()
    for (const row of previous ?? []) {
        previousByKey.set(rowKey(row), row)
    }

    const rows: CompareRow[] = current.map((row) => ({
        service_name: row.service_name,
        name: row.name,
        current: row,
        previous: previousByKey.get(rowKey(row)) ?? null,
    }))

    // Append rows that existed in the previous window but disappeared in the current window —
    // useful for spotting fully regressed call sites.
    const currentKeys = new Set(current.map(rowKey))
    for (const row of previous ?? []) {
        const key = rowKey(row)
        if (!currentKeys.has(key)) {
            rows.push({
                service_name: row.service_name,
                name: row.name,
                current: null,
                previous: row,
            })
        }
    }

    return rows
}

interface DeltaProps {
    current: number | null | undefined
    previous: number | null | undefined
    /** When true, an increase is treated as bad (red). For latency/errors. */
    higherIsWorse?: boolean
    format?: (value: number) => string
}

function Delta({ current, previous, higherIsWorse, format }: DeltaProps): JSX.Element | null {
    if (previous === null || previous === undefined || current === null || current === undefined) {
        return null
    }
    if (previous === 0 && current === 0) {
        return null
    }
    const diff = current - previous
    if (diff === 0) {
        return <span className="text-xs text-muted">—</span>
    }
    const pct = previous === 0 ? null : (diff / previous) * 100
    const sign = diff > 0 ? '+' : ''
    // When `higherIsWorse` is undefined the metric is informational (e.g. count) and the
    // delta is shown without a good/bad value judgement — neutral muted text.
    const colorClass =
        higherIsWorse === undefined
            ? 'text-muted'
            : (higherIsWorse ? diff > 0 : diff < 0)
              ? 'text-danger'
              : 'text-success'
    const label =
        pct === null ? `${sign}${format ? format(diff) : humanFriendlyNumber(diff)}` : `${sign}${pct.toFixed(1)}%`
    return (
        <Tooltip
            title={`${format ? format(previous) : humanFriendlyNumber(previous)} → ${
                format ? format(current) : humanFriendlyNumber(current)
            }`}
        >
            <span className={`text-xs ${colorClass}`}>{label}</span>
        </Tooltip>
    )
}

export interface TraceCompareTableProps {
    current: AggregatedSpanRow[]
    previous: AggregatedSpanRow[] | null
    loading: boolean
    onRowClick?: (row: { service_name: string; name: string }) => void
}

export function TraceCompareTable({ current, previous, loading, onRowClick }: TraceCompareTableProps): JSX.Element {
    const rows = useMemo(() => buildRows(current, previous), [current, previous])

    const columns: LemonTableColumns<CompareRow> = [
        {
            title: 'Service',
            key: 'service_name',
            render: (_, row) => <span className="font-mono text-xs">{row.service_name}</span>,
            sorter: (a, b) => a.service_name.localeCompare(b.service_name),
        },
        {
            title: 'Span name',
            key: 'name',
            render: (_, row) => <span className="font-mono text-xs">{row.name}</span>,
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Count',
            key: 'count',
            align: 'right',
            render: (_, row) => (
                <div className="flex flex-col items-end">
                    <span>{row.current ? humanFriendlyNumber(row.current.count) : '—'}</span>
                    <Delta current={row.current?.count} previous={row.previous?.count} />
                </div>
            ),
            sorter: (a, b) => (a.current?.count ?? 0) - (b.current?.count ?? 0),
        },
        {
            title: 'p50',
            key: 'p50',
            align: 'right',
            render: (_, row) => (
                <div className="flex flex-col items-end">
                    <span>{row.current ? formatDuration(row.current.p50_duration_nano) : '—'}</span>
                    <Delta
                        current={row.current?.p50_duration_nano}
                        previous={row.previous?.p50_duration_nano}
                        higherIsWorse
                        format={formatDuration}
                    />
                </div>
            ),
            sorter: (a, b) => (a.current?.p50_duration_nano ?? 0) - (b.current?.p50_duration_nano ?? 0),
        },
        {
            title: 'p95',
            key: 'p95',
            align: 'right',
            render: (_, row) => (
                <div className="flex flex-col items-end">
                    <span>{row.current ? formatDuration(row.current.p95_duration_nano) : '—'}</span>
                    <Delta
                        current={row.current?.p95_duration_nano}
                        previous={row.previous?.p95_duration_nano}
                        higherIsWorse
                        format={formatDuration}
                    />
                </div>
            ),
            sorter: (a, b) => (a.current?.p95_duration_nano ?? 0) - (b.current?.p95_duration_nano ?? 0),
        },
        {
            title: 'Errors',
            key: 'errors',
            align: 'right',
            render: (_, row) => (
                <div className="flex flex-col items-end">
                    <span>{row.current ? humanFriendlyNumber(row.current.error_count) : '—'}</span>
                    <Delta current={row.current?.error_count} previous={row.previous?.error_count} higherIsWorse />
                </div>
            ),
            sorter: (a, b) => (a.current?.error_count ?? 0) - (b.current?.error_count ?? 0),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={rows}
            loading={loading}
            rowKey={(row) => rowKey(row)}
            emptyState="No spans found"
            defaultSorting={{ columnKey: 'count', order: -1 }}
            onRow={
                onRowClick
                    ? (row) => ({
                          onClick: () => onRowClick({ service_name: row.service_name, name: row.name }),
                          className: 'cursor-pointer',
                      })
                    : undefined
            }
        />
    )
}
