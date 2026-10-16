import { useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useEffect, useMemo, useRef } from 'react'
import { List, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'

import { getTimelineTicks } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceDialogLogic, type TraceDialogTimeline } from './traceDialogLogic'
import { TraceDialogMoreSpansRow } from './TraceDialogMoreSpansRow'
import type { TraceDialogRow } from './traceDialogRows'
import { TraceDialogSpanRow } from './TraceDialogSpanRow'

const ROW_HEIGHT = 32

interface SpanListRowData {
    spanRows: TraceDialogRow[]
    descendantCounts: Map<string, number>
    collapsedSpanIds: Set<string>
    timeline: TraceDialogTimeline
    serviceColorMap: Map<string, number>
    selectedSpanId: string | null
    openedSpanId: string | null
    openedAtUs: number | null
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onShowAll: (spanId: string) => void
}

function SpanListRow({
    ariaAttributes,
    index,
    style,
    spanRows,
    descendantCounts,
    collapsedSpanIds,
    selectedSpanId,
    openedSpanId,
    openedAtUs,
    onShowAll,
    ...rowProps
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & SpanListRowData): JSX.Element {
    const row = spanRows[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div {...ariaAttributes} style={style}>
            {row.kind === 'more' ? (
                <TraceDialogMoreSpansRow parent={row.parent} hiddenCount={row.hiddenCount} onShowAll={onShowAll} />
            ) : (
                <TraceDialogSpanRow
                    node={row.node}
                    isSelected={row.node.span.span_id === selectedSpanId}
                    openedAtUs={row.node.span.span_id === openedSpanId ? openedAtUs : null}
                    descendantCount={descendantCounts.get(row.node.span.span_id) ?? 0}
                    isCollapsed={collapsedSpanIds.has(row.node.span.span_id)}
                    {...rowProps}
                />
            )}
        </div>
    )
}

export function TraceDialogSpanTree(): JSX.Element {
    const {
        spanRows,
        spanTree,
        collapsedSpanIds,
        timeline,
        serviceColorMap,
        selectedSpan,
        missingParentSpanId,
        trace,
        openedAtUs,
    } = useValues(traceDialogLogic)
    const { selectSpan, toggleSpanCollapsed, showAllChildren } = useActions(traceDialogLogic)
    const listRef = useListRef(null)
    const openedSpanId = trace?.spanId ?? null

    const openedIndex = useMemo(
        () =>
            openedSpanId
                ? spanRows.findIndex((row) => row.kind === 'span' && row.node.span.span_id === openedSpanId)
                : -1,
        [spanRows, openedSpanId]
    )
    // Bring the span that emitted the log into view. The list measures itself only after it mounts, so
    // an early scroll is lost: retry each time the rendered rows change until the span is visible, then
    // leave scrolling to the user.
    const revealedIndexRef = useRef<number | null>(null)
    const revealOpenedSpan = useCallback(
        (visibleRows: { startIndex: number; stopIndex: number }): void => {
            if (openedIndex < 0 || revealedIndexRef.current === openedIndex) {
                return
            }
            if (openedIndex >= visibleRows.startIndex && openedIndex <= visibleRows.stopIndex) {
                revealedIndexRef.current = openedIndex
                return
            }
            listRef.current?.scrollToRow({ index: openedIndex, align: 'center' })
        },
        [openedIndex, listRef]
    )
    // Keep each span J and K step to in view. While the opened span still waits for its centred reveal
    // above, this leaves it alone.
    const selectedSpanId = missingParentSpanId ?? selectedSpan?.span_id ?? null
    useEffect(() => {
        const index = spanRows.findIndex((row) => row.kind === 'span' && row.node.span.span_id === selectedSpanId)
        if (index >= 0 && (selectedSpanId !== openedSpanId || revealedIndexRef.current !== null)) {
            listRef.current?.scrollToRow({ index, align: 'smart' })
        }
    }, [spanRows, selectedSpanId, openedSpanId, listRef])

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center text-[11px] text-muted border-b py-1" aria-hidden>
                <span className="w-16 shrink-0 px-2">Start</span>
                <span className="w-80 shrink-0">Span</span>
                <span className="relative grow h-4">
                    {getTimelineTicks(timeline.durationUs).map((tickUs) => (
                        <span
                            key={tickUs}
                            className="absolute -translate-x-1/2 font-mono"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${(tickUs / timeline.durationUs) * 100}%` }}
                            translate="no"
                        >
                            {formatDuration(tickUs * 1_000)}
                        </span>
                    ))}
                </span>
                <span className="w-20 shrink-0 px-2 text-right">Duration</span>
            </div>
            <div className="flex-1 min-h-0">
                <AutoSizer
                    renderProp={({ width, height }: SizeProps) => (
                        <List<SpanListRowData>
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width, height }}
                            overscanCount={10}
                            rowCount={spanRows.length}
                            rowHeight={ROW_HEIGHT}
                            rowComponent={SpanListRow}
                            rowProps={{
                                spanRows,
                                descendantCounts: spanTree.descendantCounts,
                                collapsedSpanIds,
                                timeline,
                                serviceColorMap,
                                selectedSpanId,
                                openedSpanId,
                                openedAtUs,
                                onSelect: selectSpan,
                                onToggleCollapsed: toggleSpanCollapsed,
                                onShowAll: showAllChildren,
                            }}
                            listRef={listRef}
                            onRowsRendered={revealOpenedSpan}
                        />
                    )}
                />
            </div>
        </div>
    )
}
