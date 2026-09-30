import { CSSProperties, ReactNode, useCallback, useMemo, useRef } from 'react'
import { List, useListRef } from 'react-window'

import { LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { TZLabel } from 'lib/components/TZLabel'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { cn } from 'lib/utils/css-classes'

import { TRACING_DATE_FORMAT, TRACING_DISPLAY_TIMEZONE, TRACING_TIME_FORMAT } from '../../dateFormats'
import type { ErrorScope } from '../../errorCorrelation'
import type { SpanErrorBadge } from '../../spanErrorsLogic'
import { formatDuration } from '../../TraceWaterfallView'
import type { TracingOrderBy, TracingOrderDirection } from '../../tracingFiltersLogic'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from '../../types'
import type { Span } from '../../types'
import { TableCell } from '../TableColumns/TableCell'
import { TableHeaderCell } from '../TableColumns/TableHeaderCell'
import { ResizableColumns, useResizableColumns } from '../TableColumns/useResizableColumns'
import {
    SpanColumnConfig,
    spanAttributeValue,
    spanColumnKey,
    spanColumnLabel,
    spanColumnSortKey,
    toSpanColumnSpecs,
} from './spanColumns'
import { SpanErrorsBadge } from './SpanErrorsBadge'
import { SpanRowActions } from './SpanRowActions'

const ROW_HEIGHT = 36
const HEADER_HEIGHT = 32
// Trigger the next page once the bottom of the rendered window is within this many rows of the end.
const LOAD_MORE_THRESHOLD = 10

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

/** Badges rows that hit errors. Absent when the feature is off, and then no column. */
export interface SpanErrors {
    /** What each row badges, by span uuid. A row the map does not hold carries no badge. */
    badges: Map<string, SpanErrorBadge>
    /** The tier travels with the click so the drawer opens on the scope the badge just named. */
    onShow: (span: Span, scope: ErrorScope) => void
}

interface VirtualizedSpanListProps extends SortProps {
    dataSource: Span[]
    loading: boolean
    onRowClick: (span: Span) => void
    onVisibleRowRangeChange: (startIndex: number, stopIndex: number) => void
    hasMoreToLoad?: boolean
    onLoadMore?: () => void
    emptyState?: ReactNode
    spanErrors?: SpanErrors
    spanColumns: SpanColumnConfig[]
}

interface SpanRowProps {
    dataSource: Span[]
    spanColumns: SpanColumnConfig[]
    widths: Record<string, number>
    onRowClick: (span: Span) => void
    spanErrors: SpanErrors | undefined
}

/** Header cell wired to the shared resize handle. `sort` marks the column as server-sortable. */
function SpanHeaderCell({
    columnKey,
    label,
    resizeLabel,
    widths,
    columns,
    sort,
}: {
    columnKey: string
    /** Omit for a column with no heading, e.g. row actions. */
    label?: string
    /** Names the column to assistive tech on the resize handle when it has no visible heading. */
    resizeLabel?: string
    widths: Record<string, number>
    columns: ResizableColumns
    sort?: { column: TracingOrderBy } & SortProps
}): JSX.Element {
    const active = sort ? sort.orderBy === sort.column : false
    return (
        <TableHeaderCell
            width={widths[columnKey]}
            resize={columns.resizeHandleProps(columnKey, label ?? resizeLabel ?? columnKey)}
        >
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
    spanColumns,
    widths,
    columns,
    showSpanErrors,
    orderBy,
    orderDirection,
    onSort,
}: {
    spanColumns: SpanColumnConfig[]
    widths: Record<string, number>
    columns: ResizableColumns
    showSpanErrors: boolean
} & SortProps): JSX.Element {
    const shared = { widths, columns }
    const sortProps = { orderBy, orderDirection, onSort }
    return (
        <div
            className="flex items-center border-b border-border bg-surface-secondary font-medium text-muted"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: HEADER_HEIGHT }}
        >
            {spanColumns.map((column) => {
                const sortKey = spanColumnSortKey(column)
                const key = spanColumnKey(column)
                return (
                    <SpanHeaderCell
                        key={key}
                        {...shared}
                        columnKey={key}
                        label={spanColumnLabel(column)}
                        sort={sortKey ? { column: sortKey, ...sortProps } : undefined}
                    />
                )
            })}
            {/* The error badge needs no heading; its tooltip says what the count means. */}
            {showSpanErrors && <SpanHeaderCell {...shared} columnKey="spanErrors" resizeLabel="Errors" />}
            {/* Row actions need no heading. */}
            <SpanHeaderCell {...shared} columnKey="actions" />
        </div>
    )
}

function spanCellContent(column: SpanColumnConfig, span: Span): JSX.Element | null {
    switch (column.type) {
        case 'timestamp':
            return (
                <span className="font-mono">
                    <TZLabel
                        time={span.timestamp}
                        formatDate={TRACING_DATE_FORMAT}
                        formatTime={TRACING_TIME_FORMAT}
                        displayTimezone={TRACING_DISPLAY_TIMEZONE}
                        showSeconds
                    />
                </span>
            )
        case 'name':
            return (
                <span className="flex items-center gap-2 truncate">
                    <span className="truncate">{span.name}</span>
                    {isRootSpan(span) && (
                        <LemonTag type="highlight" size="small">
                            trace
                        </LemonTag>
                    )}
                </span>
            )
        case 'service':
            return <LemonTag>{span.service_name}</LemonTag>
        case 'kind':
            return <>{SPAN_KIND_LABELS[span.kind] ?? span.kind}</>
        case 'duration':
            return <>{formatDuration(span.duration_nano)}</>
        case 'status': {
            const status = STATUS_CODE_LABELS[span.status_code] ?? {
                label: String(span.status_code),
                type: 'default' as const,
            }
            return <LemonTag type={status.type}>{status.label}</LemonTag>
        }
        case 'traceId':
            return <span className="font-mono">{span.trace_id.substring(0, 16)}...</span>
        case 'attribute': {
            const value = spanAttributeValue(span, column.attributeKey)
            // Empty rather than a placeholder, so a column added for one service is not noise on the rest.
            return value ? (
                <span className="font-mono" title={value}>
                    {value}
                </span>
            ) : null
        }
    }
}

function SpanRow({
    span,
    spanColumns,
    widths,
    spanErrors,
    onClick,
}: {
    span: Span
    spanColumns: SpanColumnConfig[]
    widths: Record<string, number>
    spanErrors: SpanErrors | undefined
    onClick: () => void
}): JSX.Element {
    const errorBadge = spanErrors?.badges.get(span.uuid)

    return (
        <div
            className="flex items-center cursor-pointer border-b border-border hover:bg-surface-primary-hover"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: ROW_HEIGHT }}
            onClick={onClick}
            // Only a key press on the row itself opens it. A press on a button inside the row
            // bubbles here too, and taking it would cancel that button's own click.
            onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
                    e.preventDefault()
                    onClick()
                }
            }}
            role="button"
            tabIndex={0}
        >
            {spanColumns.map((column) => {
                const key = spanColumnKey(column)
                return (
                    <TableCell key={key} width={widths[key]}>
                        {spanCellContent(column, span)}
                    </TableCell>
                )
            })}
            {spanErrors && (
                <TableCell width={widths.spanErrors}>
                    {errorBadge && (
                        <SpanErrorsBadge
                            tier={errorBadge.tier}
                            errorCount={errorBadge.count}
                            alsoInSession={errorBadge.alsoInSession}
                            onClick={() => spanErrors.onShow(span, errorBadge.tier)}
                        />
                    )}
                </TableCell>
            )}
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
    spanColumns,
    widths,
    spanErrors,
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
            <SpanRow
                span={span}
                spanColumns={spanColumns}
                widths={widths}
                spanErrors={spanErrors}
                onClick={() => onRowClick(span)}
            />
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
    spanErrors,
    spanColumns,
    orderBy,
    orderDirection,
    onSort,
}: VirtualizedSpanListProps): JSX.Element {
    // Tracks the last range we dispatched so we don't fire on every overscan tick.
    const lastVisibleRangeRef = useRef<{ startIndex: number; stopIndex: number } | null>(null)

    const listRef = useListRef(null)
    // The dependency is the boolean, not `spanErrors`: that object gets a new identity every time
    // error counts arrive, which would break the specs identity useResizableColumns caches on.
    const showSpanErrors = !!spanErrors
    const specs = useMemo(() => toSpanColumnSpecs(spanColumns, { showSpanErrors }), [spanColumns, showSpanErrors])
    const columns = useResizableColumns(TABLE_KEY, specs)

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
                                    spanColumns={spanColumns}
                                    widths={widths}
                                    columns={columns}
                                    showSpanErrors={showSpanErrors}
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
                                    rowProps={{ dataSource, spanColumns, widths, spanErrors, onRowClick }}
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
