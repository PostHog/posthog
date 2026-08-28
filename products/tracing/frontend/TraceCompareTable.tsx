import { CSSProperties, useMemo, useState } from 'react'
import { List } from 'react-window'

import { LemonSegmentedButton, LemonTag, LemonTagType, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AggregatedSpanRow } from '~/queries/schema/schema-general'

import { buildRows, changeMagnitude, type CompareRow, type CompareRowStatus, isLowSample } from './compareUtils'
import { formatDuration } from './TraceWaterfallView'

const ROW_HEIGHT = 44
const HEADER_HEIGHT = 32

// Fixed column widths (px). The span-name and service columns flex to share the remaining space.
const COL_WIDTH = {
    count: 110,
    p50: 110,
    p95: 110,
    errors: 110,
} as const

// Minimum widths the flexing columns keep before the row scrolls horizontally. Span name takes the
// larger share of spare width, but Service now grows too instead of truncating on wide viewports.
const NAME_MIN_WIDTH = 200
const NAME_GROW = 3
const SERVICE_MIN_WIDTH = 160
const SERVICE_GROW = 1
const MIN_ROW_WIDTH =
    Object.values(COL_WIDTH).reduce((sum, width) => sum + width, 0) + NAME_MIN_WIDTH + SERVICE_MIN_WIDTH

// 'change' is the default: biggest p95 movers (both directions) first, so the table answers
// "what changed?" without any clicking. Column header clicks switch to plain value sorts.
type SortColumn = 'change' | 'service_name' | 'name' | 'count' | 'p50' | 'p95' | 'errors'
type SortOrder = 1 | -1

type StatusFilter = 'all' | CompareRowStatus

// One record drives both the quick-filter bar (label) and the row badge (tagType, New/Gone only).
const STATUS_META: Partial<Record<CompareRowStatus, { label: string; tagType?: LemonTagType }>> = {
    regressed: { label: 'Regressed' },
    improved: { label: 'Improved' },
    new: { label: 'New', tagType: 'success' },
    gone: { label: 'Gone', tagType: 'muted' },
}
const FILTERABLE_STATUSES = Object.keys(STATUS_META) as CompareRowStatus[]

const SORTERS: Record<SortColumn, (a: CompareRow, b: CompareRow) => number> = {
    change: (a, b) => changeMagnitude(a) - changeMagnitude(b),
    service_name: (a, b) => a.service_name.localeCompare(b.service_name),
    name: (a, b) => a.name.localeCompare(b.name),
    count: (a, b) => (a.current?.count ?? 0) - (b.current?.count ?? 0),
    p50: (a, b) => (a.current?.p50_duration_nano ?? 0) - (b.current?.p50_duration_nano ?? 0),
    p95: (a, b) => (a.current?.p95_duration_nano ?? 0) - (b.current?.p95_duration_nano ?? 0),
    errors: (a, b) => (a.current?.error_count ?? 0) - (b.current?.error_count ?? 0),
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

function Cell({
    width,
    minWidth,
    grow,
    align,
    children,
}: {
    width?: number
    minWidth?: number
    grow?: number
    align?: 'right'
    children: React.ReactNode
}): JSX.Element {
    const flex = width === undefined
    return (
        <div
            className={cn('shrink-0 truncate px-2 text-xs', align === 'right' && 'text-right')}
            style={
                // eslint-disable-next-line react/forbid-dom-props
                flex ? { flexGrow: grow ?? 1, flexBasis: 0, minWidth: minWidth ?? NAME_MIN_WIDTH } : { width }
            }
        >
            {children}
        </div>
    )
}

interface SortProps {
    sortColumn: SortColumn
    sortOrder: SortOrder
    onSort: (column: SortColumn) => void
}

function SortableHeaderCell({
    column,
    label,
    width,
    minWidth,
    grow,
    align,
    sortColumn,
    sortOrder,
    onSort,
}: {
    column: SortColumn
    label: string
    width?: number
    minWidth?: number
    grow?: number
    align?: 'right'
} & SortProps): JSX.Element {
    const active = sortColumn === column
    return (
        <Cell width={width} minWidth={minWidth} grow={grow} align={align}>
            <button
                type="button"
                className={cn(
                    'flex items-center cursor-pointer hover:text-default',
                    align === 'right' && 'ml-auto',
                    active && 'text-default'
                )}
                onClick={() => onSort(column)}
                data-attr={`tracing-compare-sort-${column}`}
            >
                <span>{label}</span>
                <SortingIndicator order={active ? sortOrder : null} />
            </button>
        </Cell>
    )
}

function CompareRowHeader({ sortColumn, sortOrder, onSort }: SortProps): JSX.Element {
    return (
        <div
            className="flex items-center border-b border-border bg-surface-secondary font-medium text-muted"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: HEADER_HEIGHT }}
        >
            <SortableHeaderCell
                column="service_name"
                label="Service"
                minWidth={SERVICE_MIN_WIDTH}
                grow={SERVICE_GROW}
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
            <SortableHeaderCell
                column="name"
                label="Span name"
                minWidth={NAME_MIN_WIDTH}
                grow={NAME_GROW}
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
            <SortableHeaderCell
                column="count"
                label="Count"
                width={COL_WIDTH.count}
                align="right"
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
            <SortableHeaderCell
                column="p50"
                label="p50"
                width={COL_WIDTH.p50}
                align="right"
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
            <SortableHeaderCell
                column="p95"
                label="p95"
                width={COL_WIDTH.p95}
                align="right"
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
            <SortableHeaderCell
                column="errors"
                label="Errors"
                width={COL_WIDTH.errors}
                align="right"
                sortColumn={sortColumn}
                sortOrder={sortOrder}
                onSort={onSort}
            />
        </div>
    )
}

interface CompareRowProps {
    dataSource: CompareRow[]
    onRowClick?: (row: { service_name: string; name: string }) => void
}

function CompareListRow({
    ariaAttributes,
    index,
    style,
    dataSource,
    onRowClick,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & CompareRowProps): JSX.Element {
    const row = dataSource[index]
    const statusTag = STATUS_META[row.status]?.tagType ? STATUS_META[row.status] : undefined
    // Low-sample rows classify as unchanged; color-judging their deltas red/green would
    // contradict that in the same row, so they render neutral like the count delta.
    const judged = isLowSample(row) ? undefined : true
    return (
        <div
            {...ariaAttributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            data-index={index}
            data-row-key={`${row.service_name}:${row.name}`}
        >
            <div
                className={cn(
                    'flex items-center border-b border-border hover:bg-surface-primary-hover',
                    onRowClick && 'cursor-pointer',
                    // Vanished call sites: keep them readable but visually secondary.
                    !row.current && 'opacity-60'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: ROW_HEIGHT }}
                onClick={onRowClick ? () => onRowClick({ service_name: row.service_name, name: row.name }) : undefined}
                onKeyDown={
                    onRowClick
                        ? (e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  onRowClick({ service_name: row.service_name, name: row.name })
                              }
                          }
                        : undefined
                }
                role={onRowClick ? 'button' : undefined}
                tabIndex={onRowClick ? 0 : undefined}
            >
                <Cell minWidth={SERVICE_MIN_WIDTH} grow={SERVICE_GROW}>
                    <span className="font-mono">{row.service_name}</span>
                </Cell>
                <Cell minWidth={NAME_MIN_WIDTH} grow={NAME_GROW}>
                    <span className="inline-flex items-center gap-1.5 max-w-full">
                        <span className="font-mono truncate">{row.name}</span>
                        {statusTag && (
                            <LemonTag type={statusTag.tagType} size="small">
                                {statusTag.label}
                            </LemonTag>
                        )}
                    </span>
                </Cell>
                <Cell width={COL_WIDTH.count} align="right">
                    <div className="flex flex-col items-end">
                        <span>{row.current ? humanFriendlyNumber(row.current.count) : '—'}</span>
                        <Delta current={row.current?.count} previous={row.previous?.count} />
                    </div>
                </Cell>
                <Cell width={COL_WIDTH.p50} align="right">
                    <div className="flex flex-col items-end">
                        <span>{row.current ? formatDuration(row.current.p50_duration_nano) : '—'}</span>
                        <Delta
                            current={row.current?.p50_duration_nano}
                            previous={row.previous?.p50_duration_nano}
                            higherIsWorse={judged}
                            format={formatDuration}
                        />
                    </div>
                </Cell>
                <Cell width={COL_WIDTH.p95} align="right">
                    <div className="flex flex-col items-end">
                        <span>{row.current ? formatDuration(row.current.p95_duration_nano) : '—'}</span>
                        <Delta
                            current={row.current?.p95_duration_nano}
                            previous={row.previous?.p95_duration_nano}
                            higherIsWorse={judged}
                            format={formatDuration}
                        />
                    </div>
                </Cell>
                <Cell width={COL_WIDTH.errors} align="right">
                    <div className="flex flex-col items-end">
                        <span>{row.current ? humanFriendlyNumber(row.current.error_count) : '—'}</span>
                        <Delta
                            current={row.current?.error_count}
                            previous={row.previous?.error_count}
                            higherIsWorse={judged}
                        />
                    </div>
                </Cell>
            </div>
        </div>
    )
}

export interface TraceCompareTableProps {
    current: AggregatedSpanRow[]
    previous: AggregatedSpanRow[] | null
    loading: boolean
    onRowClick?: (row: { service_name: string; name: string }) => void
}

export function TraceCompareTable({ current, previous, loading, onRowClick }: TraceCompareTableProps): JSX.Element {
    const [sortColumn, setSortColumn] = useState<SortColumn>('change')
    const [sortOrder, setSortOrder] = useState<SortOrder>(-1)
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

    const { allRows, statusCounts } = useMemo(() => {
        const built = buildRows(current, previous)
        const counts: Record<CompareRowStatus, number> = { regressed: 0, improved: 0, new: 0, gone: 0, unchanged: 0 }
        for (const row of built) {
            counts[row.status] += 1
        }
        return { allRows: built, statusCounts: counts }
    }, [current, previous])

    // A refetch can empty the selected bucket (e.g. baseline preset change) — fall back to
    // All instead of rendering a selected-but-disabled option over an empty table.
    const activeStatusFilter: StatusFilter =
        statusFilter === 'all' || statusCounts[statusFilter] > 0 ? statusFilter : 'all'

    const rows = useMemo(() => {
        const filtered =
            activeStatusFilter === 'all' ? allRows : allRows.filter((row) => row.status === activeStatusFilter)
        const sorter = SORTERS[sortColumn]
        return [...filtered].sort((a, b) => sorter(a, b) * sortOrder)
    }, [allRows, activeStatusFilter, sortColumn, sortOrder])

    const onSort = (column: SortColumn): void => {
        if (column === sortColumn) {
            setSortOrder((order) => (order === 1 ? -1 : 1))
        } else {
            setSortColumn(column)
            setSortOrder(-1)
        }
    }

    const rowProps = useMemo((): CompareRowProps => ({ dataSource: rows, onRowClick }), [rows, onRowClick])

    if (allRows.length === 0) {
        return (
            <div className="flex items-center justify-center p-8 text-muted border rounded bg-bg-light">
                {loading ? <Spinner className="text-2xl" /> : 'No spans found'}
            </div>
        )
    }

    const statusOptions = [
        { value: 'all' as StatusFilter, label: `All (${allRows.length})` },
        ...FILTERABLE_STATUSES.map((status) => ({
            value: status as StatusFilter,
            label: `${STATUS_META[status]?.label} (${statusCounts[status]})`,
            disabledReason: statusCounts[status] === 0 ? 'No spans in this bucket' : undefined,
        })),
    ]

    // Without a baseline dataset there are no buckets to filter — every row is 'unchanged'.
    const hasBaseline = previous !== null

    return (
        <div className="flex flex-col flex-1 min-h-0 gap-2" data-attr="tracing-compare-table">
            {hasBaseline && (
                <div className="flex items-center gap-2 flex-wrap" data-attr="tracing-compare-status-filter">
                    <LemonSegmentedButton<StatusFilter>
                        size="small"
                        value={activeStatusFilter}
                        onChange={setStatusFilter}
                        options={statusOptions}
                    />
                    {sortColumn !== 'change' && (
                        <Link
                            className="text-xs"
                            onClick={() => onSort('change')}
                            data-attr="tracing-compare-sort-change"
                        >
                            Sort by biggest change
                        </Link>
                    )}
                </div>
            )}
            <div className="flex flex-col flex-1 min-h-0 bg-bg-light border rounded overflow-hidden">
                <AutoSizer
                    renderProp={({ width, height }: SizeProps) => {
                        if (!width || !height) {
                            return null
                        }
                        const rowWidth = Math.max(width, MIN_ROW_WIDTH)
                        return (
                            // The viewport is fixed to the available box; the inner content can be wider
                            // (MIN_ROW_WIDTH) so columns scroll horizontally and rows align with the header.
                            // eslint-disable-next-line react/forbid-dom-props
                            <div className="overflow-x-auto" style={{ width, height }}>
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <div style={{ width: rowWidth }}>
                                    <CompareRowHeader sortColumn={sortColumn} sortOrder={sortOrder} onSort={onSort} />
                                    {rows.length === 0 ? (
                                        <div className="flex items-center justify-center p-8 text-muted">
                                            No spans in this bucket
                                        </div>
                                    ) : (
                                        <List<CompareRowProps>
                                            style={{ height: height - HEADER_HEIGHT, width: rowWidth }}
                                            overscanCount={10}
                                            rowCount={rows.length}
                                            rowHeight={ROW_HEIGHT}
                                            rowComponent={CompareListRow}
                                            rowProps={rowProps}
                                        />
                                    )}
                                </div>
                            </div>
                        )
                    }}
                />
            </div>
        </div>
    )
}
