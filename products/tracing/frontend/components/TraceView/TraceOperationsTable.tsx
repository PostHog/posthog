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

// The table lists the main contributors and the span tree shows every span, so the table shows only the top 5
// operations by the sorted column. The note under the table says how many operations there are in all.
const MAX_OPERATIONS = 5

const DEFAULT_SORT: VirtualizedSort = { columnKey: 'total', order: -1 }

const HIGHLIGHTED_ROW_CLASS = 'bg-accent-highlight-secondary font-semibold'

export interface TraceOperationsTableProps {
    /** Sorted by total time descending, as summarizeTraceOperations returns them. */
    operations: TraceOperation[]
    highlightedOperationKey: string | null
    /** Called with the row's key, or null when the highlighted row is clicked again. */
    onHighlightOperation: (operationKey: string | null) => void
    /** The trace has spans that are not loaded yet, so the counts do not cover the whole trace. */
    partial?: boolean
    /** Drop the Avg and p50 columns for a narrow container. The operation's tooltip shows them instead. */
    compact?: boolean
    /** What the Share column divides by: the trace duration, or the duration of the inspected span. */
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

function withTimings(title: string, operation: TraceOperation, compact: boolean): string {
    return compact
        ? `${title}\navg ${formatDuration(operation.avg_duration_nano)} · p50 ${formatDuration(operation.p50_duration_nano)}`
        : title
}

// The service name shares the Operation cell instead of a column of its own. Together the default widths
// fit in 520px, the width of the drawer next to an open side panel. The compact set drops Avg and p50, so
// that Share stays in view in the span inspector, which is narrower. Operation grows into the width the
// numeric columns leave, and a person can drag it wider to read a long name.
const SPANS_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'count',
    title: 'Spans',
    width: 72,
    align: 'right',
    sorter: (a, b) => a.count - b.count,
    render: (row) => humanFriendlyNumber(row.count),
}

const TOTAL_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'total',
    title: 'Total',
    width: 80,
    align: 'right',
    tooltip: 'Sum of span durations. Nested spans count in both parent and child.',
    sorter: (a, b) => a.total_duration_nano - b.total_duration_nano,
    render: (row) => <span className="font-mono">{formatDuration(row.total_duration_nano)}</span>,
}

const AVG_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'avg',
    title: 'Avg',
    width: 72,
    align: 'right',
    sorter: (a, b) => a.avg_duration_nano - b.avg_duration_nano,
    render: (row) => <span className="font-mono">{formatDuration(row.avg_duration_nano)}</span>,
}

const P50_COLUMN: VirtualizedTableColumn<TraceOperation> = {
    key: 'p50',
    title: 'p50',
    width: 72,
    align: 'right',
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
    trace: shareColumn('Total as a share of the trace duration. Nested spans can push this above 100%.'),
    span: shareColumn("Total as a share of this span's duration. Nested spans can push this above 100%."),
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
                width: 144,
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
                            className="block w-full font-mono text-left truncate cursor-pointer"
                            title={withTimings(highlightTitle(isHighlighted), row, compact)}
                            onClick={(event) => {
                                // Stop here so that the row handler does not toggle the highlight a second time.
                                event.stopPropagation()
                                onHighlightOperation(nextHighlightKey(row, highlightedOperationKey))
                            }}
                        >
                            <span title={withTimings(`${row.service_name} ${row.name}`, row, compact)} translate="no">
                                <span className="text-muted">{row.service_name}</span> {row.name}
                            </span>
                        </button>
                    )
                },
            },
            SPANS_COLUMN,
            TOTAL_COLUMN,
            ...(compact ? [] : [AVG_COLUMN, P50_COLUMN]),
            SHARE_COLUMNS[shareOf],
        ],
        [highlightedOperationKey, onHighlightOperation, compact, shareOf]
    )
    // Sort the whole list before the cap. Otherwise a sort by Spans only reorders the five operations with
    // the largest totals, and the most-called operations of the trace stay hidden.
    const visibleOperations = useMemo((): TraceOperation[] => {
        const sorter = columns.find((column) => column.key === sort?.columnKey)?.sorter
        if (!sort || !sorter) {
            return operations.slice(0, MAX_OPERATIONS)
        }
        return [...operations].sort((a, b) => sorter(a, b) * sort.order).slice(0, MAX_OPERATIONS)
    }, [operations, columns, sort])
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
                    sort={sort}
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
