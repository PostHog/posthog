import { CSSProperties, ReactNode, useCallback, useMemo, useRef } from 'react'
import { List, useListRef } from 'react-window'

import { LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { cn } from 'lib/utils/css-classes'

import { formatDuration } from '../../TraceWaterfallView'
import type { TracingOrderBy, TracingOrderDirection } from '../../tracingFiltersLogic'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from '../../types'
import type { Span } from '../../types'
import { SpanRowActions } from './SpanRowActions'

const ROW_HEIGHT = 36
const HEADER_HEIGHT = 32
// Trigger the next page once the bottom of the rendered window is within this many rows of the end.
const LOAD_MORE_THRESHOLD = 10

// Fixed column widths (px). The name column flexes to fill the remaining space.
const COL_WIDTH = {
    timestamp: 190,
    service: 150,
    kind: 90,
    duration: 90,
    status: 80,
    traceId: 140,
    actions: 130,
} as const

// Minimum width the flexing name column keeps before the row scrolls horizontally on narrow viewports.
const NAME_MIN_WIDTH = 160
// Minimum content width: every fixed column at full width plus a sensible name column. Derived so it
// can't drift when columns are added or removed.
const MIN_ROW_WIDTH = Object.values(COL_WIDTH).reduce((sum, width) => sum + width, 0) + NAME_MIN_WIDTH

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
    onRowClick: (span: Span) => void
}

function Cell({ width, children }: { width?: number; children: React.ReactNode }): JSX.Element {
    return (
        <div
            className={cn('shrink-0 truncate px-2 text-xs', width === undefined && 'flex-1 min-w-0')}
            // eslint-disable-next-line react/forbid-dom-props
            style={width !== undefined ? { width } : undefined}
        >
            {children}
        </div>
    )
}

function SortableHeaderCell({
    column,
    label,
    width,
    orderBy,
    orderDirection,
    onSort,
}: { column: TracingOrderBy; label: string; width: number } & SortProps): JSX.Element {
    const active = orderBy === column
    return (
        <Cell width={width}>
            <button
                type="button"
                className={cn('flex items-center cursor-pointer hover:text-default', active && 'text-default')}
                onClick={() => onSort(column)}
                data-attr={`tracing-sort-${column}`}
            >
                <span>{label}</span>
                {/* Neutral icon when inactive (so the column reads as sortable), directional arrow
                    once active — order 1 = ASC, -1 = DESC, matching LemonTable's convention. */}
                <SortingIndicator order={active ? (orderDirection === 'ASC' ? 1 : -1) : null} />
            </button>
        </Cell>
    )
}

function SpanRowHeader({ orderBy, orderDirection, onSort }: SortProps): JSX.Element {
    return (
        <div
            className="flex items-center border-b border-border bg-surface-secondary font-medium text-muted"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: HEADER_HEIGHT }}
        >
            <SortableHeaderCell
                column="timestamp"
                label="Timestamp"
                width={COL_WIDTH.timestamp}
                orderBy={orderBy}
                orderDirection={orderDirection}
                onSort={onSort}
            />
            <Cell>Name</Cell>
            <Cell width={COL_WIDTH.service}>Service</Cell>
            <Cell width={COL_WIDTH.kind}>Kind</Cell>
            <SortableHeaderCell
                column="duration"
                label="Duration"
                width={COL_WIDTH.duration}
                orderBy={orderBy}
                orderDirection={orderDirection}
                onSort={onSort}
            />
            <Cell width={COL_WIDTH.status}>Status</Cell>
            <Cell width={COL_WIDTH.traceId}>Trace ID</Cell>
            <Cell width={COL_WIDTH.actions}> </Cell>
        </div>
    )
}

function SpanRow({ span, onClick }: { span: Span; onClick: () => void }): JSX.Element {
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
            <Cell width={COL_WIDTH.timestamp}>{new Date(span.timestamp).toLocaleString()}</Cell>
            <Cell>
                <span className="flex items-center gap-2 truncate">
                    <span className="truncate">{span.name}</span>
                    {isRootSpan(span) && (
                        <LemonTag type="highlight" size="small">
                            trace
                        </LemonTag>
                    )}
                </span>
            </Cell>
            <Cell width={COL_WIDTH.service}>
                <LemonTag>{span.service_name}</LemonTag>
            </Cell>
            <Cell width={COL_WIDTH.kind}>{SPAN_KIND_LABELS[span.kind] ?? span.kind}</Cell>
            <Cell width={COL_WIDTH.duration}>{formatDuration(span.duration_nano)}</Cell>
            <Cell width={COL_WIDTH.status}>
                <LemonTag type={status.type}>{status.label}</LemonTag>
            </Cell>
            <Cell width={COL_WIDTH.traceId}>
                <span className="font-mono">{span.trace_id.substring(0, 16)}...</span>
            </Cell>
            <Cell width={COL_WIDTH.actions}>
                <SpanRowActions span={span} onViewTrace={onClick} />
            </Cell>
        </div>
    )
}

function SpanListRow({
    ariaAttributes,
    index,
    style,
    dataSource,
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
            <SpanRow span={span} onClick={() => onRowClick(span)} />
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

    const rowProps = useMemo((): SpanRowProps => ({ dataSource, onRowClick }), [dataSource, onRowClick])

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
                    const rowWidth = Math.max(width, MIN_ROW_WIDTH)
                    return (
                        // The viewport is fixed to the available box; the inner content can be wider
                        // (MIN_ROW_WIDTH) so columns scroll horizontally and rows align with the header.
                        // eslint-disable-next-line react/forbid-dom-props
                        <div className="overflow-x-auto" style={{ width, height }}>
                            {/* eslint-disable-next-line react/forbid-dom-props */}
                            <div style={{ width: rowWidth }}>
                                <SpanRowHeader orderBy={orderBy} orderDirection={orderDirection} onSort={onSort} />
                                <List<SpanRowProps>
                                    style={{ height: height - HEADER_HEIGHT, width: rowWidth }}
                                    overscanCount={10}
                                    rowCount={dataSource.length}
                                    rowHeight={ROW_HEIGHT}
                                    rowComponent={SpanListRow}
                                    rowProps={rowProps}
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
