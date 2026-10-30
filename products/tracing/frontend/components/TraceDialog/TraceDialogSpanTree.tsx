import { useActions, useValues } from 'kea'
import { CSSProperties, KeyboardEvent, PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { List, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'

import { getTimelineTicks } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { TraceLoadMoreFooter } from '../TraceView/TraceLoadMoreFooter'
import {
    type TraceRunToggleMethod,
    traceViewLogic,
    type TraceViewSurface,
    type TraceViewTimeline,
} from '../TraceView/traceViewLogic'
import { TraceDialogMoreSpansRow } from './TraceDialogMoreSpansRow'
import type { TraceDialogSource } from './traceDialogOpenLogic'
import { rowSpanNode, type TraceDialogRow } from './traceDialogRows'
import { TraceDialogSpanRow } from './TraceDialogSpanRow'

const ROW_HEIGHT = 32
const LOAD_MORE_THRESHOLD = 10
const SCROLL_KEYS = new Set(['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'End', 'Home', ' '])

interface SpanListRowData {
    spanRows: TraceDialogRow[]
    descendantCounts: Map<string, number>
    collapsedSpanIds: Set<string>
    timeline: TraceViewTimeline
    serviceColorMap: Map<string, number>
    selectedSpanId: string | null
    openedSpanId: string | null
    openedAtUs: number | null
    openedFrom: TraceDialogSource | null
    /** Per row, whether it stands for a span of the highlighted operation. Null when nothing dims. */
    operationRowMatches: boolean[] | null
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onToggleChain: (spanId: string) => void
    onToggleRun: (spanId: string, method: TraceRunToggleMethod) => void
    onShowAll: (spanId: string) => void
    onShowFewer: (spanId: string) => void
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
    openedFrom,
    operationRowMatches,
    onShowAll,
    onShowFewer,
    ...rowProps
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & SpanListRowData): JSX.Element {
    const row = spanRows[index]
    const isDimmed = operationRowMatches != null && !operationRowMatches[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div {...ariaAttributes} style={style}>
            {row.kind === 'more' || row.kind === 'fewer' ? (
                <TraceDialogMoreSpansRow
                    row={row}
                    isDimmed={isDimmed}
                    onShowAll={onShowAll}
                    onShowFewer={onShowFewer}
                />
            ) : (
                <SpanChainOrRunRow
                    row={row}
                    selectedSpanId={selectedSpanId}
                    openedSpanId={openedSpanId}
                    openedAtUs={openedAtUs}
                    openedFrom={openedFrom}
                    isDimmed={isDimmed}
                    descendantCounts={descendantCounts}
                    collapsedSpanIds={collapsedSpanIds}
                    rowProps={rowProps}
                />
            )}
        </div>
    )
}

function SpanChainOrRunRow({
    row,
    selectedSpanId,
    openedSpanId,
    openedAtUs,
    openedFrom,
    isDimmed,
    descendantCounts,
    collapsedSpanIds,
    rowProps,
}: {
    row: Extract<TraceDialogRow, { kind: 'span' | 'chain' | 'run' }>
    selectedSpanId: string | null
    openedSpanId: string | null
    openedAtUs: number | null
    openedFrom: TraceDialogSource | null
    isDimmed: boolean
    descendantCounts: Map<string, number>
    collapsedSpanIds: Set<string>
    rowProps: Pick<
        SpanListRowData,
        'timeline' | 'serviceColorMap' | 'onSelect' | 'onToggleCollapsed' | 'onToggleChain' | 'onToggleRun'
    >
}): JSX.Element {
    const spanId = (row.kind === 'span' ? row.node : row.nodes[0]).span.span_id
    return (
        <TraceDialogSpanRow
            row={row}
            isSelected={spanId === selectedSpanId}
            openedAtUs={spanId === openedSpanId ? openedAtUs : null}
            openedFrom={spanId === openedSpanId ? openedFrom : null}
            isDimmed={isDimmed}
            descendantCount={descendantCounts.get(spanId) ?? 0}
            isCollapsed={collapsedSpanIds.has(spanId)}
            {...rowProps}
        />
    )
}

function scrolledPastAncestors(row: TraceDialogRow | undefined): TraceDialogRow[] {
    const ancestors: TraceDialogRow[] = []
    for (let ancestor = row?.parentRow ?? null; ancestor; ancestor = ancestor.parentRow) {
        ancestors.push(ancestor)
    }
    return ancestors.reverse()
}

function rowLabel(row: TraceDialogRow): string {
    if (row.kind === 'chain') {
        return `${row.nodes[0].span.name} › … › ${row.nodes[row.nodes.length - 1].span.name}`
    }
    return row.kind === 'span' ? row.node.span.name : ''
}

const MAX_PINNED_ANCESTORS = 4

export interface TraceDialogSpanTreeProps {
    /** Where the tree sits, for analytics. */
    surface: TraceViewSurface
    openedFrom: TraceDialogSource | null
    openedAtUs: number | null
    hasMore?: boolean
    loadingMore?: boolean
    onLoadMore?: () => void
    /** Dim the rows outside the highlighted operation. Off while the inspector, which explains the dimming, is hidden. */
    showOperationHighlight?: boolean
}

export function TraceDialogSpanTree({
    surface,
    openedFrom,
    openedAtUs,
    hasMore = false,
    loadingMore = false,
    onLoadMore,
    showOperationHighlight = true,
}: TraceDialogSpanTreeProps): JSX.Element {
    const {
        spanRows,
        spanTree,
        collapsedSpanIds,
        timeline,
        serviceColorMap,
        selectedSpan,
        missingParentSpanId,
        pinnedSpanId: openedSpanId,
        highlightedOperationKey,
        operationRowMatches,
        firstOperationRowIndex,
        summary,
        foldedRunStartIds,
        shownTraceCount,
    } = useValues(traceViewLogic)
    const { selectSpan, toggleSpanCollapsed, toggleChain, toggleRun, showAllChildren, showFewerChildren, runsShown } =
        useActions(traceViewLogic)
    const onToggleRun = useCallback(
        (spanId: string, method: TraceRunToggleMethod): void => toggleRun(spanId, method, surface),
        [toggleRun, surface]
    )
    // The logic sends its event once per trace. This reports when folded runs come on screen, and again for each
    // new trace, because the next trace's runs can replace this one's without a render of the empty list between.
    const showsFoldedRuns = foldedRunStartIds.size > 0
    useEffect(() => {
        if (showsFoldedRuns) {
            runsShown(surface)
        }
    }, [showsFoldedRuns, shownTraceCount, runsShown, surface])
    const [topIndex, setTopIndex] = useState(0)
    const listRef = useListRef(null)

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
    // Folded runs can make a large trace a few rows tall, so the end of the list is often in view without a
    // scroll. Paging on that alone would load the whole trace on its own, so the next page waits for the person
    // to scroll, and the button below the list stays for the rest. A page whose spans all fold into runs on
    // screen adds no row, so the guard counts loaded spans and not rows.
    // The guard belongs to one shown trace, so a scroll in the previous trace cannot page this one. It starts
    // again on the logic's trace count and not on an empty list, because the logic can hand over the next
    // trace's spans before a render shows the empty list.
    const pagingRef = useRef({ shownTraceCount, personScrolled: false, lastRequestedSpanCount: -1 })
    const pagingGuard = useCallback((): typeof pagingRef.current => {
        if (pagingRef.current.shownTraceCount !== shownTraceCount) {
            pagingRef.current = { shownTraceCount, personScrolled: false, lastRequestedSpanCount: -1 }
        }
        return pagingRef.current
    }, [shownTraceCount])
    const lastVisibleIndexRef = useRef(-1)
    const loadMoreAfterScroll = useCallback((): void => {
        const guard = pagingGuard()
        if (
            !guard.personScrolled ||
            !onLoadMore ||
            !hasMore ||
            loadingMore ||
            lastVisibleIndexRef.current < spanRows.length - 1 - LOAD_MORE_THRESHOLD ||
            guard.lastRequestedSpanCount === summary.spanCount
        ) {
            return
        }
        guard.personScrolled = false
        guard.lastRequestedSpanCount = summary.spanCount
        onLoadMore()
    }, [pagingGuard, onLoadMore, hasMore, loadingMore, spanRows.length, summary.spanCount])
    const onPersonScroll = useCallback((): void => {
        pagingGuard().personScrolled = true
        loadMoreAfterScroll()
    }, [pagingGuard, loadMoreAfterScroll])
    const onRowsRendered = useCallback(
        (visibleRows: { startIndex: number; stopIndex: number }): void => {
            setTopIndex(visibleRows.startIndex)
            lastVisibleIndexRef.current = visibleRows.stopIndex
            loadMoreAfterScroll()
            if (openedIndex < 0 || revealedIndexRef.current === openedIndex) {
                return
            }
            if (openedIndex >= visibleRows.startIndex && openedIndex <= visibleRows.stopIndex) {
                revealedIndexRef.current = openedIndex
                return
            }
            listRef.current?.scrollToRow({ index: openedIndex, align: 'center' })
        },
        [openedIndex, listRef, loadMoreAfterScroll]
    )
    // Keep each span J and K step to in view. While the opened span still waits for its centred reveal
    // above, this leaves it alone.
    const selectedSpanId = missingParentSpanId ?? selectedSpan?.span_id ?? null
    const lastSelectionInputsRef = useRef({ spanTree, selectedSpanId })
    useEffect(() => {
        const last = lastSelectionInputsRef.current
        lastSelectionInputsRef.current = { spanTree, selectedSpanId }
        // A page of spans loads when the person scrolls near the end of the list. It changes the rows but not
        // the selection, so the list stays where the person scrolled it, or where an operation highlight put it.
        if (spanTree !== last.spanTree && selectedSpanId === last.selectedSpanId) {
            return
        }
        const index = spanRows.findIndex((row) => rowSpanNode(row)?.span.span_id === selectedSpanId)
        if (index >= 0 && (selectedSpanId !== openedSpanId || revealedIndexRef.current !== null)) {
            listRef.current?.scrollToRow({ index, align: 'smart' })
        }
    }, [spanRows, spanTree, selectedSpanId, openedSpanId, listRef])
    // The view's key handler stops J and K before the list sees them, so a step reaches the list as a new
    // selection. A new selection among the same spans counts as the person's own movement, so a step to the end
    // of the loaded spans pages too. New spans or a new trace do not count.
    const lastSelectionRef = useRef({ selectedSpanId, spanTree })
    useEffect(() => {
        const last = lastSelectionRef.current
        lastSelectionRef.current = { selectedSpanId, spanTree }
        if (last.spanTree === spanTree && last.selectedSpanId !== selectedSpanId) {
            onPersonScroll()
        }
    }, [selectedSpanId, spanTree, onPersonScroll])
    // The first span of a large operation often sits far down the tree, so a click on the operations table
    // scrolls to it. The logic has already opened what hid it, so it is the first row of the operation. The
    // `start` alignment puts it at the top, so the rest of the operation's spans fill the list below it. The
    // ref holds the key that last scrolled, so that a later collapse, expand or page of spans does not pull
    // the list back. This effect runs after the selection scroll above, so its scroll wins when the opened
    // rows trigger both.
    const scrolledOperationKeyRef = useRef<string | null>(null)
    useEffect(() => {
        if (highlightedOperationKey == null) {
            scrolledOperationKeyRef.current = null
            return
        }
        if (scrolledOperationKeyRef.current === highlightedOperationKey || !listRef.current) {
            return
        }
        if (firstOperationRowIndex >= 0) {
            // The opened rows can move the opened span to a new index, which the reveal in `onRowsRendered`
            // reads as a span still to bring into view. The person steers the list now, so that reveal stops.
            revealedIndexRef.current = openedIndex
            listRef.current.scrollToRow({ index: firstOperationRowIndex, align: 'start' })
            scrolledOperationKeyRef.current = highlightedOperationKey
        }
    }, [highlightedOperationKey, firstOperationRowIndex, openedIndex, listRef])

    const pinnedAncestors = scrolledPastAncestors(spanRows[topIndex])
    const hiddenAncestorCount = Math.max(pinnedAncestors.length - MAX_PINNED_ANCESTORS, 0)

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center text-[11px] text-muted border-b py-1" aria-hidden>
                <span className="w-16 shrink-0 px-2">Start</span>
                <span className="w-96 shrink min-w-48">Span</span>
                <span className="relative grow min-w-16 h-4">
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
            {pinnedAncestors.length > 0 && (
                <div
                    className="flex items-center gap-1 h-7 px-2 border-b text-xs text-muted bg-surface-secondary min-w-0 overflow-hidden"
                    data-attr="trace-dialog-pinned-ancestors"
                >
                    <span className="shrink-0">Inside</span>
                    {hiddenAncestorCount > 0 && (
                        <span className="shrink-0">
                            <span translate="no">{hiddenAncestorCount}</span> more ›
                        </span>
                    )}
                    {pinnedAncestors.slice(hiddenAncestorCount).map((ancestor, i) => {
                        const node = rowSpanNode(ancestor)
                        return node ? (
                            <span key={node.span.span_id} className="flex items-center gap-1 min-w-0">
                                {i > 0 && <span aria-hidden>›</span>}
                                <button
                                    type="button"
                                    className="truncate font-mono text-primary hover:underline"
                                    onClick={() => {
                                        selectSpan(node.span.span_id)
                                        // Selecting an already selected span changes nothing the scroll effect watches.
                                        listRef.current?.scrollToRow({
                                            index: spanRows.indexOf(ancestor),
                                            align: 'smart',
                                        })
                                    }}
                                    translate="no"
                                >
                                    {rowLabel(ancestor)}
                                </button>
                            </span>
                        ) : null
                    })}
                </div>
            )}
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
                                openedFrom,
                                operationRowMatches: showOperationHighlight ? operationRowMatches : null,
                                onSelect: selectSpan,
                                onToggleCollapsed: toggleSpanCollapsed,
                                onToggleChain: toggleChain,
                                onToggleRun,
                                onShowAll: showAllChildren,
                                onShowFewer: showFewerChildren,
                            }}
                            listRef={listRef}
                            onRowsRendered={onRowsRendered}
                            onWheel={onPersonScroll}
                            onTouchMove={onPersonScroll}
                            onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
                                if (SCROLL_KEYS.has(event.key)) {
                                    onPersonScroll()
                                }
                            }}
                            onPointerDown={(event: PointerEvent<HTMLDivElement>) => {
                                // A press past the content width lands on the scrollbar.
                                if (event.nativeEvent.offsetX >= event.currentTarget.clientWidth) {
                                    onPersonScroll()
                                }
                            }}
                        />
                    )}
                />
            </div>
            {hasMore && <TraceLoadMoreFooter loadingMore={loadingMore} onLoadMore={onLoadMore} />}
        </div>
    )
}
