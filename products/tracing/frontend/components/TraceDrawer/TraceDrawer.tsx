import { useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { LemonButton, LemonTabs, LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { JSONViewer } from 'lib/components/JSONViewer'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { useKeepMountedWhileOpen } from '../../hooks/useKeepMountedWhileOpen'
import { getQueryText } from '../../spanSummary'
import { absoluteTraceUrl } from '../../traceLinks'
import { buildServiceColorMap, formatDuration, TraceWaterfallView } from '../../TraceWaterfallView'
import type { Span } from '../../types'
import { ExpandedSpanContent } from '../VirtualizedSpanList/ExpandedSpanContent'
import { SpanLogsTab } from './SpanLogsTab'
import { SpanSummaryHeader } from './SpanSummaryHeader'

type InspectorTab = 'attributes' | 'query' | 'logs' | 'raw'

// Below this the inspector's content (the attribute KVP tables) stops being readable; clamp so a
// drag can't crush it. The max is a flex `max-w` so a too-wide drag can't starve the waterfall.
const MIN_INSPECTOR_WIDTH = 320

export interface TraceDrawerProps {
    isOpen: boolean
    traceId: string | null
    /** Timestamp hint echoed into copy-links so cold loads can bound the lookup. */
    ts: string | null
    spans: Span[]
    loading: boolean
    /** The open trace has more spans than the loaded pages — drives the waterfall's infinite scroll. */
    hasMoreSpans?: boolean
    /** A next page of spans is being fetched (shows a bottom spinner without the full overlay). */
    loadingMoreSpans?: boolean
    onLoadMoreSpans?: () => void
    selectedSpanId: string | null
    onSelectSpan: (spanId: string | null) => void
    onClose: () => void
}

// Master-detail split: waterfall on the left drives the span inspector on the right — the same
// list→detail relationship the span list has with this drawer, one level down. Tabs live *inside*
// the inspector (Attributes / Logs), not at the drawer level — so the waterfall stays visible while
// you read a span's attributes or its correlated logs.
export function TraceDrawer({
    isOpen,
    traceId,
    ts,
    spans,
    loading,
    hasMoreSpans = false,
    loadingMoreSpans = false,
    onLoadMoreSpans,
    selectedSpanId,
    onSelectSpan,
    onClose,
}: TraceDrawerProps): JSX.Element | null {
    // Waterfall|inspector split. Persisted so a user's preferred split sticks across traces;
    // desiredSize is null until the first drag, leaving the responsive default (w-2/5) in place.
    // One props object feeds both the value-read and the <Resizer>, so the logicKey can't desync.
    const inspectorRef = useRef<HTMLDivElement>(null)
    const inspectorResizerProps: ResizerLogicProps = {
        logicKey: 'tracing-span-inspector',
        placement: 'left',
        containerRef: inspectorRef,
        persistent: true,
    }
    const { desiredSize: inspectorWidth } = useValues(resizerLogic(inspectorResizerProps))
    const [inspectorTab, setInspectorTab] = useState<InspectorTab>('attributes')

    // Resolve the inspected span outside render churn: a resize drag re-renders this component on
    // every mousemove, and these scans are O(spans) — memoize so they only run when data/selection change.
    const rootSpan = useMemo(() => spans.find((span) => span.is_root_span) ?? spans[0] ?? null, [spans])
    const selectedSpan = useMemo(
        () => (selectedSpanId ? (spans.find((span) => span.span_id === selectedSpanId) ?? null) : null),
        [spans, selectedSpanId]
    )
    // Shared with the waterfall so a service is the same color in the bars and the summary header.
    const serviceColorMap = useMemo(() => buildServiceColorMap(spans), [spans])

    // The inspector always shows something: the selected span, falling back to the root.
    const inspectedSpan = selectedSpan ?? rootSpan

    // Gate mounting so a closed drawer holds no react-modal portal (and its listener surface).
    const shouldRender = useKeepMountedWhileOpen(isOpen)
    if (!shouldRender) {
        return null
    }

    // Only DB spans carry a query; the Query tab appears only when one is present.
    const queryText = inspectedSpan ? getQueryText(inspectedSpan) : null
    // The Query tab is conditional, so if it's the active tab and the user selects a span without a
    // query, fall back to Attributes — otherwise activeKey would point at a tab LemonTabs has dropped
    // and the inspector body would render blank. (Preference is preserved: a DB span re-shows Query.)
    const activeInspectorTab: InspectorTab = inspectorTab === 'query' && !queryText ? 'attributes' : inspectorTab

    return (
        <LemonDrawer
            isOpen={isOpen}
            onClose={onClose}
            width="90vw"
            resizable
            data-attr="tracing-trace-drawer"
            title={
                <div className="flex items-center gap-2 min-w-0">
                    <span className="truncate">{rootSpan?.name ?? 'Trace'}</span>
                    {rootSpan && <LemonTag>{formatDuration(rootSpan.duration_nano)}</LemonTag>}
                    <span className="font-mono text-xs text-muted truncate">{traceId}</span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconLink />}
                        tooltip="Copy link to this trace"
                        data-attr="tracing-drawer-copy-link"
                        onClick={() =>
                            traceId &&
                            void copyToClipboard(
                                absoluteTraceUrl({ traceId, spanId: selectedSpanId, ts }),
                                'trace link'
                            )
                        }
                    />
                </div>
            }
        >
            <div className="relative min-h-32 flex gap-4 items-start">
                {loading && <SpinnerOverlay />}
                <div className="flex-1 min-w-0">
                    {/* Keyed by trace so a new trace resets selection + scroll state. */}
                    <TraceWaterfallView
                        key={traceId ?? ''}
                        spans={spans}
                        selectedSpanId={selectedSpanId}
                        onSpanSelect={onSelectSpan}
                        hasMore={hasMoreSpans}
                        loadingMore={loadingMoreSpans}
                        onLoadMore={onLoadMoreSpans}
                    />
                </div>
                <div
                    ref={inspectorRef}
                    className={cn(
                        'relative shrink-0 border-l border-border pl-4 max-w-[70%]',
                        inspectorWidth == null && 'w-2/5'
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={
                        inspectorWidth != null ? { width: Math.max(MIN_INSPECTOR_WIDTH, inspectorWidth) } : undefined
                    }
                    data-attr="tracing-span-inspector"
                >
                    <Resizer {...inspectorResizerProps} />
                    {inspectedSpan ? (
                        <>
                            <SpanSummaryHeader span={inspectedSpan} serviceColorMap={serviceColorMap} />
                            <LemonTabs
                                activeKey={activeInspectorTab}
                                onChange={setInspectorTab}
                                data-attr="tracing-inspector-tabs"
                                tabs={[
                                    {
                                        key: 'attributes',
                                        label: 'Attributes',
                                        // The summary header carries the headline facts, so the tab
                                        // shows only the user attributes (no duplicate details table).
                                        content: <ExpandedSpanContent span={inspectedSpan} showDetails={false} />,
                                    },
                                    // Conditional (LemonTabs ignores falsy entries): only DB spans have a query.
                                    queryText
                                        ? {
                                              key: 'query',
                                              label: 'Query',
                                              content: (
                                                  <CodeSnippet
                                                      language={Language.SQL}
                                                      wrap
                                                      maxLinesWithoutExpansion={40}
                                                  >
                                                      {queryText}
                                                  </CodeSnippet>
                                              ),
                                          }
                                        : null,
                                    {
                                        key: 'logs',
                                        label: 'Logs',
                                        // Not keyed by span: the embedded viewer (keyed by trace_id) and the memoized
                                        // pinned filter re-query in place when the selected span changes, so a remount
                                        // would only churn its logics and lose scroll.
                                        content: <SpanLogsTab span={inspectedSpan} />,
                                    },
                                    {
                                        key: 'raw',
                                        label: 'Raw',
                                        // Interactive tree, matching the logs viewer's raw view (LogDetailsModal)
                                        // for cross-pane consistency. The span as the frontend holds it.
                                        content: <JSONViewer src={inspectedSpan} collapsed={2} sortKeys />,
                                    },
                                ]}
                            />
                        </>
                    ) : (
                        <div className="text-muted p-4">No spans in this trace</div>
                    )}
                </div>
            </div>
        </LemonDrawer>
    )
}
