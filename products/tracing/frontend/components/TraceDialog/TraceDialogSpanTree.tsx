import { useActions, useValues } from 'kea'
import { CSSProperties, useEffect } from 'react'
import { List, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'

import { getTimelineTicks, type SpanNode } from 'products/tracing/frontend/spanTree'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceDialogLogic, type TraceDialogTimeline } from './traceDialogLogic'
import { TraceDialogSpanRow } from './TraceDialogSpanRow'

const ROW_HEIGHT = 32

interface SpanListRowData {
    flatSpans: SpanNode[]
    timeline: TraceDialogTimeline
    serviceColorMap: Map<string, number>
    selectedSpanId: string | null
    openedSpanId: string | null
    openedAtUs: number | null
    onSelect: (spanId: string) => void
}

function SpanListRow({
    ariaAttributes,
    index,
    style,
    flatSpans,
    selectedSpanId,
    openedSpanId,
    openedAtUs,
    ...rowProps
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & SpanListRowData): JSX.Element {
    const node = flatSpans[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div {...ariaAttributes} style={style}>
            <TraceDialogSpanRow
                node={node}
                isSelected={node.span.span_id === selectedSpanId}
                openedAtUs={node.span.span_id === openedSpanId ? openedAtUs : null}
                {...rowProps}
            />
        </div>
    )
}

export function TraceDialogSpanTree(): JSX.Element {
    const { flatSpans, timeline, serviceColorMap, selectedSpanId, trace, openedAtUs } = useValues(traceDialogLogic)
    const { selectSpan } = useActions(traceDialogLogic)
    const listRef = useListRef(null)
    const openedSpanId = trace?.spanId ?? null

    // Bring the span that emitted the log into view once the spans arrive.
    useEffect(() => {
        if (!openedSpanId) {
            return
        }
        const index = flatSpans.findIndex((node) => node.span.span_id === openedSpanId)
        if (index >= 0) {
            listRef.current?.scrollToRow({ index, align: 'center' })
        }
    }, [flatSpans, openedSpanId, listRef])

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
                            rowCount={flatSpans.length}
                            rowHeight={ROW_HEIGHT}
                            rowComponent={SpanListRow}
                            rowProps={{
                                flatSpans,
                                timeline,
                                serviceColorMap,
                                selectedSpanId,
                                openedSpanId,
                                openedAtUs,
                                onSelect: selectSpan,
                            }}
                            listRef={listRef}
                        />
                    )}
                />
            </div>
        </div>
    )
}
