import { useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { LemonButton, LemonTabs, LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { useKeepMountedWhileOpen } from '../../hooks/useKeepMountedWhileOpen'
import { absoluteTraceUrl } from '../../traceLinks'
import { buildServiceColorMap, formatDuration, TraceWaterfallView } from '../../TraceWaterfallView'
import type { Span } from '../../types'
import { ExpandedSpanContent } from '../VirtualizedSpanList/ExpandedSpanContent'
import { SpanLogsTab } from './SpanLogsTab'
import { SpanSummaryHeader } from './SpanSummaryHeader'

type InspectorTab = 'attributes' | 'logs'

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

    // Gate mounting so a closed drawer holds no react-modal portal (and its listener surface).
    const shouldRender = useKeepMountedWhileOpen(isOpen)
    if (!shouldRender) {
        return null
    }

    // The inspector always shows something: the selected span, falling back to the root.
    const inspectedSpan = selectedSpan ?? rootSpan

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
                                activeKey={inspectorTab}
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
                                    {
                                        key: 'logs',
                                        label: 'Logs',
                                        // Not keyed by span: the embedded viewer (keyed by trace_id) and the memoized
                                        // pinned filter re-query in place when the selected span changes, so a remount
                                        // would only churn its logics and lose scroll.
                                        content: <SpanLogsTab span={inspectedSpan} />,
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
