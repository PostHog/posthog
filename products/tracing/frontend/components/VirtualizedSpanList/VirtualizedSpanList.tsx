import { CSSProperties, ReactNode, useCallback, useRef } from 'react'
import { List, useListRef } from 'react-window'

import { LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { TZLabel } from 'lib/components/TZLabel'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { cn } from 'lib/utils/css-classes'

import { TRACING_DATE_FORMAT, TRACING_DISPLAY_TIMEZONE, TRACING_TIME_FORMAT } from '../../dateFormats'
import { formatDuration } from '../../TraceWaterfallView'
import type { TracingOrderBy, TracingOrderDirection } from '../../tracingFiltersLogic'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from '../../types'
import type { Span } from '../../types'
import { ResizableColumnSpec } from '../TableColumns/columnWidths'
import { TableCell } from '../TableColumns/TableCell'
import { TableHeaderCell } from '../TableColumns/TableHeaderCell'
import { ResizableColumns, useResizableColumns } from '../TableColumns/useResizableColumns'
import { SpanRowActions } from './SpanRowActions'

const ROW_HEIGHT = 36
const HEADER_HEIGHT = 32
// Trigger the next page once the bottom of the rendered window is within this many rows of the end.
const LOAD_MORE_THRESHOLD = 10

// Default column widths (px), in render order. Anyone can drag a column wider or narrower from here.
const SPAN_COLUMNS: ResizableColumnSpec[] = [
    { key: 'timestamp', width: 215 },
    { key: 'name', width: 320, grow: true },
    { key: 'service', width: 200 },
    { key: 'kind', width: 90 },
    { key: 'duration', width: 90 },
    { key: 'status', width: 80 },
    { key: 'traceId', width: 140 },
    { key: 'actions', width: 130 },
]
// pinned: identifies stored column widths — renaming resets everyone's widths
const TABLE_KEY = 'spans'

function isRootSpan(span: Span): boolean {
    return !span.parent_span_id
}

interface SortProps {
    orderBy: TracingOrderBy
    orderDirection: TracingOrderDirection
    onSort: (column: TracingOrderBy) => void
}

interface VirtualizedSpanListProps extends SortProps {
    dataSource: Span[]
    loading: boolean
    onRowClick: (span: Span) => void
    onVisibleRowRangeChange: (startIndex: number, stopIndex: number) => void
    hasMoreToLoad?: boolean
    onLoadMore?: () => void
    emptyState?: ReactNode
}

interface SpanRowProps {
    dataSource: Span[]
    widths: Record<string, number>
    onRowClick: (span: Span) => void
}

/** Header cell wired to the shared resize handle. `sort` marks the column as server-sortable. */
function SpanHeaderCell({
    columnKey,
    label,
    widths,
    columns,
    sort,
}: {
    columnKey: string
    /** Omit for a column with no heading, e.g. row actions. */
    label?: string
    widths: Record<string, number>
    columns: ResizableColumns
    sort?: { column: TracingOrderBy } & SortProps
}): JSX.Element {
    const active = sort ? sort.orderBy === sort.column : false
    return (
        <TableHeaderCell width={widths[columnKey]} resize={columns.resizeHandleProps(columnKey, label ?? columnKey)}>
            {sort ? (
                <button
                    type="button"
                    className={cn('flex items-center cursor-pointer hover:text-default', active && 'text-default')}
                    onClick={() => sort.onSort(sort.column)}
                    data-attr={`tracing-sort-${sort.column}`}
                >
                    <span>{label}</span>
                    {/* Neutral icon when inactive (so the column reads as sortable), directional arrow
                        once active — order 1 = ASC, -1 = DESC, matching LemonTable's convention. */}
                    <SortingIndicator order={active ? (sort.orderDirection === 'ASC' ? 1 : -1) : null} />
                </button>
            ) : (
                (label ?? null)
            )}
        </TableHeaderCell>
    )
}

function SpanRowHeader({
    widths,
    columns,
    orderBy,
    orderDirection,
    onSort,
}: { widths: Record<string, number>; columns: ResizableColumns } & SortProps): JSX.Element {
    const shared = { widths, columns }
    const sortProps = { orderBy, orderDirection, onSort }
    return (
        <div
            className="flex items-center border-b border-border bg-surface-secondary font-medium text-muted"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: HEADER_HEIGHT }}
        >
            <SpanHeaderCell
                {...shared}
                columnKey="timestamp"
                label="Timestamp"
                sort={{ column: 'timestamp', ...sortProps }}
            />
            <SpanHeaderCell {...shared} columnKey="name" label="Name" />
            <SpanHeaderCell {...shared} columnKey="service" label="Service" />
            <SpanHeaderCell {...shared} columnKey="kind" label="Kind" />
            <SpanHeaderCell
                {...shared}
                columnKey="duration"
                label="Duration"
                sort={{ column: 'duration', ...sortProps }}
            />
            <SpanHeaderCell {...shared} columnKey="status" label="Status" />
            <SpanHeaderCell {...shared} columnKey="traceId" label="Trace ID" />
            {/* Row actions need no heading. */}
            <SpanHeaderCell {...shared} columnKey="actions" />
        </div>
    )
}

function SpanRow({
    span,
    widths,
    onClick,
}: {
    span: Span
    widths: Record<string, number>
    onClick: () => void
}): JSX.Element {
    const status = STATUS_CODE_LABELS[span.status_code] ?? { label: String(span.status_code), type: 'default' as const }

    return (
        <div
            className="flex items-center cursor-pointer border-b border-border hover:bg-surface-primary-hover"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: ROW_HEIGHT }}
            onClick={onClick}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onClick()
                }
            }}
            role="button"
            tabIndex={0}
        >
            <TableCell width={widths.timestamp}>
                <span className="font-mono">
                    <TZLabel
                        time={span.timestamp}
                        formatDate={TRACING_DATE_FORMAT}
                        formatTime={TRACING_TIME_FORMAT}
                        displayTimezone={TRACING_DISPLAY_TIMEZONE}
                        showSeconds
                    />
                </span>
            </TableCell>
            <TableCell width={widths.name}>
                <span className="flex items-center gap-2 truncate">
                    <span className="truncate">{span.name}</span>
                    {isRootSpan(span) && (
                        <LemonTag type="highlight" size="small">
                            trace
                        </LemonTag>
                    )}
                </span>
            </TableCell>
            <TableCell width={widths.service}>
                <LemonTag>{span.service_name}</LemonTag>
            </TableCell>
            <TableCell width={widths.kind}>{SPAN_KIND_LABELS[span.kind] ?? span.kind}</TableCell>
            <TableCell width={widths.duration}>{formatDuration(span.duration_nano)}</TableCell>
            <TableCell width={widths.status}>
                <LemonTag type={status.type}>{status.label}</LemonTag>
            </TableCell>
            <TableCell width={widths.traceId}>
                <span className="font-mono">{span.trace_id.substring(0, 16)}...</span>
            </TableCell>
            <TableCell width={widths.actions}>
                <SpanRowActions span={span} onViewTrace={onClick} />
            </TableCell>
        </div>
    )
}

function SpanListRow({
    ariaAttributes,
    index,
    style,
    dataSource,
    widths,
    onRowClick,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & SpanRowProps): JSX.Element {
    const span = dataSource[index]

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div {...ariaAttributes} style={style} data-index={index} data-row-key={span.uuid}>
            <SpanRow span={span} widths={widths} onClick={() => onRowClick(span)} />
        </div>
    )
}

export function VirtualizedSpanList({
    dataSource,
    loading,
    onRowClick,
    onVisibleRowRangeChange,
    hasMoreToLoad = false,
    onLoadMore,
    emptyState = 'No spans found',
    orderBy,
    orderDirection,
    onSort,
}: VirtualizedSpanListProps): JSX.Element {
    // Tracks the last range we dispatched so we don't fire on every overscan tick.
    const lastVisibleRangeRef = useRef<{ startIndex: number; stopIndex: number } | null>(null)

    const listRef = useListRef(null)
    const columns = useResizableColumns(TABLE_KEY, SPAN_COLUMNS)

    const handleRowsRendered = useCallback(
        (
            visibleRows: { startIndex: number; stopIndex: number },
            allRows: { startIndex: number; stopIndex: number }
        ): void => {
            if (
                onLoadMore &&
                hasMoreToLoad &&
                !loading &&
                allRows.stopIndex >= dataSource.length - 1 - LOAD_MORE_THRESHOLD
            ) {
                onLoadMore()
            }

            const prev = lastVisibleRangeRef.current
            if (!prev || prev.startIndex !== visibleRows.startIndex || prev.stopIndex !== visibleRows.stopIndex) {
                lastVisibleRangeRef.current = { startIndex: visibleRows.startIndex, stopIndex: visibleRows.stopIndex }
                onVisibleRowRangeChange(visibleRows.startIndex, visibleRows.stopIndex)
            }
        },
        [dataSource.length, hasMoreToLoad, loading, onLoadMore, onVisibleRowRangeChange]
    )

    if (dataSource.length === 0 && !loading) {
        return (
            <div className="flex items-center justify-center p-8 text-muted border rounded bg-bg-light">
                {emptyState}
            </div>
        )
    }

    return (
        <div
            className="flex flex-col flex-1 min-h-0 bg-bg-light border rounded overflow-hidden"
            data-attr="tracing-spans-table"
        >
            <AutoSizer
                renderProp={({ width, height }: SizeProps) => {
                    if (!width || !height) {
                        return null
                    }
                    const { widths, totalWidth } = columns.resolveWidths(width)
                    const rowWidth = Math.max(width, totalWidth)
                    return (
                        // The viewport is fixed to the available box; the inner content can be wider
                        // (totalWidth) so columns scroll horizontally and rows align with the header.
                        // eslint-disable-next-line react/forbid-dom-props
                        <div className="overflow-x-auto" style={{ width, height }}>
                            {/* eslint-disable-next-line react/forbid-dom-props */}
                            <div style={{ width: rowWidth }}>
                                <SpanRowHeader
                                    widths={widths}
                                    columns={columns}
                                    orderBy={orderBy}
                                    orderDirection={orderDirection}
                                    onSort={onSort}
                                />
                                <List<SpanRowProps>
                                    style={{ height: height - HEADER_HEIGHT, width: rowWidth }}
                                    overscanCount={10}
                                    rowCount={dataSource.length}
                                    rowHeight={ROW_HEIGHT}
                                    rowComponent={SpanListRow}
                                    rowProps={{ dataSource, widths, onRowClick }}
                                    onRowsRendered={handleRowsRendered}
                                    listRef={listRef}
                                />
                            </div>
                        </div>
                    )
                }}
            />
        </div>
    )
}
