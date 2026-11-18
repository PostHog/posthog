import { useMemo } from 'react'

import { LemonBanner, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { _ServiceHealthRowApi } from 'products/tracing/frontend/generated/api.schemas'

import { formatRate, HEALTH_META } from './OperationsTable'
import { VirtualizedTable, VirtualizedTableColumn } from './VirtualizedTable'

const ERROR_BAR_FULL_PCT = 10

const STATUS_ORDER = Object.keys(HEALTH_META) as _ServiceHealthRowApi['status'][]

function formatMs(value: number | null): string {
    if (value === null) {
        return '—'
    }
    return value >= 1000 ? `${humanFriendlyNumber(value / 1000, 2)}s` : `${humanFriendlyNumber(value, 1)}ms`
}

function formatPct(value: number | null): string {
    if (value === null) {
        return '—'
    }
    return `${value.toFixed(value > 0 && value < 1 ? 2 : 1)}%`
}

/** A change from the baseline, coloured by whether it is worse (up) or better (down). */
function Delta({ value, unit }: { value: number | null; unit: string }): JSX.Element | null {
    if (value === null || Math.abs(value) < 0.05) {
        return null
    }
    return (
        <span className={`text-xs ${value > 0 ? 'text-danger' : 'text-success'}`}>
            {value > 0 ? '+' : ''}
            {value.toFixed(1)}
            {unit}
        </span>
    )
}

function buildColumns(windowMs: number): VirtualizedTableColumn<_ServiceHealthRowApi>[] {
    return [
        {
            key: 'status',
            title: 'Status',
            width: 110,
            tooltip: 'Compared with the previous period of the same length.',
            sorter: (a, b) => STATUS_ORDER.indexOf(b.status) - STATUS_ORDER.indexOf(a.status),
            render: (row) => {
                const { label, tagType } = HEALTH_META[row.status]
                return (
                    <Tooltip title={row.reason || undefined}>
                        <LemonTag type={tagType} size="small">
                            {label}
                        </LemonTag>
                    </Tooltip>
                )
            },
        },
        {
            key: 'service',
            title: 'Service',
            width: 280,
            grow: true,
            sorter: (a, b) => a.service.localeCompare(b.service),
            render: (row) => <span className="font-mono">{row.service}</span>,
        },
        {
            key: 'requests',
            title: 'Requests',
            width: 110,
            align: 'right',
            tooltip: 'Root, server and consumer spans, one per request.',
            sorter: (a, b) => a.requests - b.requests,
            render: (row) => <span>{humanFriendlyNumber(row.requests)}</span>,
        },
        {
            key: 'rate',
            title: 'Req/s',
            width: 100,
            align: 'right',
            sorter: (a, b) => a.requests - b.requests,
            render: (row) => <span>{formatRate(row.requests, windowMs)}</span>,
        },
        {
            key: 'error_rate',
            title: 'Error rate',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.error_rate_pct ?? 0) - (b.error_rate_pct ?? 0),
            render: (row) => (
                <div className="flex flex-col items-end gap-0.5 w-full">
                    <span className={row.error_rate_pct ? 'text-danger' : 'text-muted'}>
                        {formatPct(row.error_rate_pct)}
                    </span>
                    {/* Scaled so 10% or more fills the bar: most services sit far below that. */}
                    <div className="h-1 w-full rounded-full bg-border" aria-hidden>
                        <div
                            className="h-1 rounded-full bg-danger"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: `${Math.min(100, ((row.error_rate_pct ?? 0) / ERROR_BAR_FULL_PCT) * 100)}%`,
                            }}
                        />
                    </div>
                    <Delta value={row.error_rate_delta_pp} unit=" pp" />
                </div>
            ),
        },
        {
            key: 'p95',
            title: 'p95',
            width: 100,
            align: 'right',
            sorter: (a, b) => (a.p95_ms ?? 0) - (b.p95_ms ?? 0),
            render: (row) => (
                <div className="flex flex-col items-end">
                    <span className="font-mono">{formatMs(row.p95_ms)}</span>
                    <Delta value={row.p95_change_pct} unit="%" />
                </div>
            ),
        },
        {
            key: 'p99',
            title: 'p99',
            width: 90,
            align: 'right',
            sorter: (a, b) => (a.p99_ms ?? 0) - (b.p99_ms ?? 0),
            render: (row) => <span className="font-mono">{formatMs(row.p99_ms)}</span>,
        },
    ]
}

export interface ServicesTableProps {
    rows: _ServiceHealthRowApi[]
    loading: boolean
    error?: boolean
    /** More services matched than the endpoint returns; only the busiest are in `rows`. */
    truncated?: boolean
    /** Services that matched before the endpoint's row limit. */
    totalServices?: number
    /** Property filters are active, and the services query doesn't apply them. */
    propertyFiltersIgnored?: boolean
    /** Length of the window the rows cover (ms), which turns request counts into a rate. */
    windowMs: number
    onRowClick?: (row: _ServiceHealthRowApi) => void
}

export function ServicesTable({
    rows,
    loading,
    error,
    truncated,
    totalServices,
    propertyFiltersIgnored,
    windowMs,
    onRowClick,
}: ServicesTableProps): JSX.Element {
    const columns = useMemo(() => buildColumns(windowMs), [windowMs])
    // With no rows the table's empty label carries the error, so the banner is only for stale rows.
    const showStaleError = error && rows.length > 0
    return (
        <div className="flex flex-col gap-2 flex-1 min-h-0">
            {showStaleError && (
                <LemonBanner type="error">
                    Couldn't refresh services. These rows are from the previous filters.
                </LemonBanner>
            )}
            {propertyFiltersIgnored && (
                <LemonBanner type="info">
                    Property filters don't apply to services yet. Rows cover every span in the date range and selected
                    services.
                </LemonBanner>
            )}
            {truncated && !showStaleError && (
                <LemonBanner type="warning">
                    Showing the {rows.length} busiest
                    {totalServices ? ` of ${humanFriendlyNumber(totalServices)}` : ''} services. Sorting only reorders
                    these. Filter by service to see the rest.
                </LemonBanner>
            )}
            <VirtualizedTable<_ServiceHealthRowApi>
                // pinned: identifies stored column widths — renaming resets everyone's widths
                tableKey="services"
                columns={columns}
                dataSource={rows}
                loading={loading}
                rowKey={(row) => row.service}
                onRowClick={onRowClick}
                defaultSort={{ columnKey: 'requests', order: -1 }}
                emptyLabel={
                    error
                        ? "Couldn't load services. Try again or change the filters."
                        : 'No services found for these filters'
                }
                data-attr="tracing-services-table"
            />
        </div>
    )
}
