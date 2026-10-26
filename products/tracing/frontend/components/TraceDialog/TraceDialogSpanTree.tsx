import { useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { List, useListRef } from 'react-window'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'

import { getTimelineTicks } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceViewLogic, type TraceViewTimeline } from '../TraceView/traceViewLogic'
import type { TraceDialogSource } from './traceDialogLogic'
import { TraceDialogMoreSpansRow } from './TraceDialogMoreSpansRow'
import { rowSpanNode, type TraceDialogRow } from './traceDialogRows'
import { TraceDialogSpanRow } from './TraceDialogSpanRow'

const ROW_HEIGHT = 32
const LOAD_MORE_THRESHOLD = 10

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
    onSelect: (spanId: string) => void
    onToggleCollapsed: (spanId: string) => void
    onToggleChain: (spanId: string) => void
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
    openedFrom,
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
                <TraceDialogMoreSpansRow row={row} onShowAll={onShowAll} />
            ) : (
                <SpanOrChainRow
                    row={row}
                    selectedSpanId={selectedSpanId}
                    openedSpanId={openedSpanId}
                    openedAtUs={openedAtUs}
                    openedFrom={openedFrom}
                    descendantCounts={descendantCounts}
                    collapsedSpanIds={collapsedSpanIds}
                    rowProps={rowProps}
                />
            )}
        </div>
    )
}

function SpanOrChainRow({
    row,
    selectedSpanId,
    openedSpanId,
    openedAtUs,
    openedFrom,
    descendantCounts,
    collapsedSpanIds,
    rowProps,
}: {
    row: Extract<TraceDialogRow, { kind: 'span' | 'chain' }>
    selectedSpanId: string | null
    openedSpanId: string | null
    openedAtUs: number | null
    openedFrom: TraceDialogSource | null
    descendantCounts: Map<string, number>
    collapsedSpanIds: Set<string>
    rowProps: Pick<SpanListRowData, 'timeline' | 'serviceColorMap' | 'onSelect' | 'onToggleCollapsed' | 'onToggleChain'>
}): JSX.Element {
    const spanId = (row.kind === 'chain' ? row.nodes[0] : row.node).span.span_id
    return (
        <TraceDialogSpanRow
            row={row}
            isSelected={spanId === selectedSpanId}
            openedAtUs={spanId === openedSpanId ? openedAtUs : null}
            openedFrom={spanId === openedSpanId ? openedFrom : null}
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
    openedFrom: TraceDialogSource | null
    openedAtUs: number | null
    hasMore?: boolean
    loadingMore?: boolean
    onLoadMore?: () => void
}

export function TraceDialogSpanTree({
    openedFrom,
    openedAtUs,
    hasMore = false,
    loadingMore = false,
    onLoadMore,
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
    } = useValues(traceViewLogic)
    const { selectSpan, toggleSpanCollapsed, toggleChain, showAllChildren } = useActions(traceViewLogic)
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
    // Fires at most once per loaded row count, so a page that adds no rows can't retrigger on every render.
    const lastRequestedRowCountRef = useRef(-1)
    const onRowsRendered = useCallback(
        (visibleRows: { startIndex: number; stopIndex: number }): void => {
            setTopIndex(visibleRows.startIndex)
            if (
                onLoadMore &&
                hasMore &&
                !loadingMore &&
                visibleRows.stopIndex >= spanRows.length - 1 - LOAD_MORE_THRESHOLD &&
                lastRequestedRowCountRef.current !== spanRows.length
            ) {
                lastRequestedRowCountRef.current = spanRows.length
                onLoadMore()
            }
            if (openedIndex < 0 || revealedIndexRef.current === openedIndex) {
                return
            }
            if (openedIndex >= visibleRows.startIndex && openedIndex <= visibleRows.stopIndex) {
                revealedIndexRef.current = openedIndex
                return
            }
            listRef.current?.scrollToRow({ index: openedIndex, align: 'center' })
        },
        [openedIndex, listRef, onLoadMore, hasMore, loadingMore, spanRows.length]
    )
    // Keep each span J and K step to in view. While the opened span still waits for its centred reveal
    // above, this leaves it alone.
    const selectedSpanId = missingParentSpanId ?? selectedSpan?.span_id ?? null
    useEffect(() => {
        const index = spanRows.findIndex((row) => rowSpanNode(row)?.span.span_id === selectedSpanId)
        if (index >= 0 && (selectedSpanId !== openedSpanId || revealedIndexRef.current !== null)) {
            listRef.current?.scrollToRow({ index, align: 'smart' })
        }
    }, [spanRows, selectedSpanId, openedSpanId, listRef])

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
                                onSelect: selectSpan,
                                onToggleCollapsed: toggleSpanCollapsed,
                                onToggleChain: toggleChain,
                                onShowAll: showAllChildren,
                            }}
                            listRef={listRef}
                            onRowsRendered={onRowsRendered}
                        />
                    )}
                />
            </div>
            {hasMore && (
                <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted border-t">
                    {loadingMore ? (
                        <>
                            <Spinner />
                            <span>Loading more spans…</span>
                        </>
                    ) : (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => onLoadMore?.()}
                            data-attr="trace-view-load-more-spans"
                        >
                            Load more spans
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
