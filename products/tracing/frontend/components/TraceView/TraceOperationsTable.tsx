import { memo, useCallback, useMemo, useState } from 'react'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { TraceOperation } from '../../traceOperations'
import { formatDuration } from '../../TraceWaterfallView'
import {
    VirtualizedSort,
    VirtualizedTable,
    VirtualizedTableColumn,
    virtualizedTableHeight,
} from '../../VirtualizedTable'
import { MIN_COLUMN_WIDTH } from '../TableColumns/columnWidths'

// The table lists the main contributors and the span tree shows every span, so the table shows only the top 5
// operations by the sorted column. The note under the table says how many operations there are in all.
const MAX_OPERATIONS = 5

const DEFAULT_SORT: VirtualizedSort = { columnKey: 'self', order: -1 }

const HIGHLIGHTED_ROW_CLASS = 'bg-accent-highlight-secondary font-semibold'

export interface TraceOperationsTableProps {
    /** Sorted by self time descending, as summarizeTraceOperations returns them. */
    operations: TraceOperation[]
    highlightedOperationKey: string | null
    /** Called with the row's key, or null when the highlighted row is clicked again. */
    onHighlightOperation: (operationKey: string | null) => void
    /** The trace has spans that are not loaded yet, so the counts do not cover the whole trace. */
    partial?: boolean
    /** Drop the Avg and p50 columns for a narrow container. The operation's tooltip shows them instead. */
    compact?: boolean
    /** What the operations cover, for the Share column's tooltip: the whole trace, or the inspected span's subtree. */
    shareOf?: 'trace' | 'span'
}

function highlightTitle(isHighlighted: boolean): string {
    return isHighlighted ? 'Clear the highlight' : 'Highlight these spans in the trace'
}

function nextHighlightKey(operation: TraceOperation, highlightedOperationKey: string | null): string | null {
    return operation.key === highlightedOperationKey ? null : operation.key
}

function operationRowKey(operation: TraceOperation): string {
    return operation.key
}

// The tooltip carries the duration numbers the columns leave out: the total always, and avg and p50 when compact.
function withTimings(title: string, operation: TraceOperation, compact: boolean): string {
    const timings = [
        ...(compact
            ? [
                  `avg ${formatDuration(operation.avg_duration_nano)}`,
                  `p50 ${formatDuration(operation.p50_duration_nano)}`,
              ]
            : []),
        `total ${formatDuration(operation.total_duration_nano)}`,
    ]
    return `${title}\n${timings.join(' · ')}`
}

// The service name shares the Operation cell instead of a column of its own. Together the default widths
// fit in 520px, the width of the drawer next to an open side panel. The compact set drops Avg and p50, so
// that Share stays in view in the span inspector, which is narrower. Operation grows into the width the
// numeric columns leave, and a person can drag it wider to read a long name. In the compact set it starts
// at the narrowest width a column can have. The numeric columns then fit the inspector at its narrowest,
// and Operation gives up width instead of pushing Share out of view.
const SPANS_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'count',
    title: 'Spans',
    width: 72,
    align: 'right',
    sorter: (a, b) => a.count - b.count,
    render: (row) => humanFriendlyNumber(row.count),
}

const SELF_TIME_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'self',
    title: 'Self time',
    width: 84,
    align: 'right',
    tooltip: 'Time these spans spend outside their child spans, so time in nested spans counts once.',
    sorter: (a, b) => a.self_time_nano - b.self_time_nano,
    render: (row) => <span className="font-mono">{formatDuration(row.self_time_nano)}</span>,
}

const AVG_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'avg',
    title: 'Avg',
    width: 72,
    align: 'right',
    tooltip: 'Average span duration, including time in child spans.',
    sorter: (a, b) => a.avg_duration_nano - b.avg_duration_nano,
    render: (row) => <span className="font-mono">{formatDuration(row.avg_duration_nano)}</span>,
}

const P50_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'p50',
    title: 'p50',
    width: 72,
    align: 'right',
    tooltip: 'Median span duration, including time in child spans.',
    sorter: (a, b) => a.p50_duration_nano - b.p50_duration_nano,
    render: (row) => <span className="font-mono">{formatDuration(row.p50_duration_nano)}</span>,
}

function shareColumn(tooltip: string): VirtualizedTableColumn<TraceOperation> {
    return {
        key: 'share',
        title: 'Share',
        width: 72,
        align: 'right',
        tooltip,
        sorter: (a, b) => a.share - b.share,
        render: (row) => `${(row.share * 100).toFixed(1)}%`,
    }
}

const SHARE_COLUMNS: Record<'trace' | 'span', VirtualizedTableColumn<TraceOperation>> = {
    trace: shareColumn('Self time as a share of the self time of every span in the trace.'),
    span: shareColumn('Self time as a share of the self time of this span and the spans under it.'),
}

// Memoized because the drawer re-renders on every mousemove of an inspector resize drag. The props stay
// the same during a drag, so the table skips that work. The columns stay the same object between renders,
// so useResizableColumns reuses the widths it resolved last time.
export const TraceOperationsTable = memo(function TraceOperationsTable({
    operations,
    highlightedOperationKey,
    onHighlightOperation,
    partial = false,
    compact = false,
    shareOf = 'trace',
}: TraceOperationsTableProps): JSX.Element {
    const [sort, setSort] = useState<VirtualizedSort | null>(DEFAULT_SORT)
    const columns = useMemo(
        (): VirtualizedTableColumn<TraceOperation>[] => [
            {
                key: 'name',
                title: 'Operation',
                width: compact ? MIN_COLUMN_WIDTH : 144,
                grow: true,
                sorter: (a, b) => a.name.localeCompare(b.name),
                render: (row) => {
                    const isHighlighted = row.key === highlightedOperationKey
                    // The row's own role="button" cannot say which operation is highlighted, so the cell
                    // holds a real button whose aria-pressed tells assistive technology.
                    return (
                        <button
                            type="button"
                            // pinned: autocapture selects on this value, so renaming it breaks saved actions
                            data-attr="tracing-trace-operations-highlight"
                            aria-pressed={isHighlighted}
                            className="block w-full font-mono text-left cursor-pointer"
                            title={withTimings(highlightTitle(isHighlighted), row, compact)}
                            onClick={(event) => {
                                // Stop here so that the row handler does not toggle the highlight a second time.
                                event.stopPropagation()
                                onHighlightOperation(nextHighlightKey(row, highlightedOperationKey))
                            }}
                        >
                            {/* The operations of one trace often share a long service name, so the name comes first
                                and keeps its width: the service truncates to nothing before the name truncates. */}
                            <span
                                className="flex min-w-0 overflow-hidden"
                                title={withTimings(`${row.service_name} ${row.name}`, row, compact)}
                                translate="no"
                            >
                                <span className="shrink-0 max-w-full truncate">{row.name}</span>
                                <span className="min-w-0 truncate pl-1.5 text-muted">{row.service_name}</span>
                            </span>
                        </button>
                    )
                },
            },
            SPANS_COLUMN,
            SELF_TIME_COLUMN,
            ...(compact ? [] : [AVG_COLUMN, P50_COLUMN]),
            SHARE_COLUMNS[shareOf],
        ],
        [highlightedOperationKey, onHighlightOperation, compact, shareOf]
    )
    // A sort by a column the table no longer shows, such as Avg after the table turns compact, falls back to the
    // default sort, so the header always marks the order the rows are in.
    const effectiveSort = useMemo(
        (): VirtualizedSort =>
            sort && columns.some((column) => column.key === sort.columnKey && column.sorter) ? sort : DEFAULT_SORT,
        [sort, columns]
    )
    // Sort the whole list before the cap. Otherwise a sort by Spans only reorders the five operations with
    // the most self time, and the most-called operations of the trace stay hidden.
    const visibleOperations = useMemo((): TraceOperation[] => {
        const sorter = columns.find((column) => column.key === effectiveSort.columnKey)?.sorter
        return sorter
            ? [...operations].sort((a, b) => sorter(a, b) * effectiveSort.order).slice(0, MAX_OPERATIONS)
            : operations.slice(0, MAX_OPERATIONS)
    }, [operations, columns, effectiveSort])
    const onRowClick = useCallback(
        (row: TraceOperation): void => onHighlightOperation(nextHighlightKey(row, highlightedOperationKey)),
        [highlightedOperationKey, onHighlightOperation]
    )
    const rowClassName = useCallback(
        (row: TraceOperation): string | undefined =>
            row.key === highlightedOperationKey ? HIGHLIGHTED_ROW_CLASS : undefined,
        [highlightedOperationKey]
    )

    return (
        <>
            {partial && <p className="text-xs text-muted mb-1">Counts cover the spans loaded so far.</p>}
            {/* VirtualizedTable needs a box of definite height. This one fits every visible row, so the table does not scroll. */}
            <div
                className="flex flex-col"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: virtualizedTableHeight(visibleOperations.length) }}
            >
                <VirtualizedTable<TraceOperation>
                    // pinned: identifies stored column widths, so renaming it resets everyone's widths
                    tableKey="trace-operations"
                    // pinned: autocapture and Playwright select on this value, so renaming it breaks them
                    data-attr="tracing-trace-operations-table"
                    columns={columns}
                    dataSource={visibleOperations}
                    loading={false}
                    rowKey={operationRowKey}
                    onRowClick={onRowClick}
                    rowClassName={rowClassName}
                    sort={effectiveSort}
                    onSortChange={setSort}
                />
            </div>
            {operations.length > MAX_OPERATIONS && (
                <p className="text-xs text-muted mt-1">
                    {`Showing ${MAX_OPERATIONS} of ${humanFriendlyNumber(operations.length)} operations.`}
                </p>
            )}
        </>
    )
})
