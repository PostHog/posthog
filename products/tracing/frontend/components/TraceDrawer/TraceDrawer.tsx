import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { LemonBanner, LemonButton, LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { buildAiEventSpans } from '../../aiEventSpans'
import type { ErrorScope } from '../../errorCorrelation'
import { useKeepMountedWhileOpen } from '../../hooks/useKeepMountedWhileOpen'
import type { TraceIdentity } from '../../traceIdentity'
import { absoluteTraceUrl } from '../../traceLinks'
import { buildServiceColorMap, formatDuration, TraceWaterfallView } from '../../TraceWaterfallView'
import type { Span, SpanInspectorTab } from '../../types'
import { SpanInspector } from '../SpanInspector/SpanInspector'
import { MissingParentSpanNotice } from './MissingParentSpanNotice'
import { TraceAiEventsCapNotice } from './TraceAiEventsCapNotice'
import { traceAiEventsLogic } from './traceAiEventsLogic'
import { TraceIdentityChips } from './TraceIdentityChips'
import { TraceLoadErrorNotice } from './TraceLoadErrorNotice'
import { TraceUnavailableNotice } from './TraceUnavailableNotice'

// Below this the inspector's content (the attribute KVP tables) stops being readable; clamp so a
// drag can't crush it. The max is a flex `max-w` so a too-wide drag can't starve the waterfall.
const MIN_INSPECTOR_WIDTH = 320

export interface TraceDrawerProps {
    isOpen: boolean
    traceId: string | null
    /** Timestamp hint echoed into copy-links so cold loads can bound the lookup. */
    ts: string | null
    spans: Span[]
    /** The person and session the trace belongs to, resolved by tracingViewerLogic. */
    identity: TraceIdentity
    /** The trace's session for the Errors tab, or null when its spans resolve to no one session. */
    sessionId: string | null
    /** Show the Errors tab, which lists the issues connected to the trace. */
    showErrorsTab: boolean
    /** Which inspector tab is open. Held in tracingViewerLogic so a caller can open one directly. */
    inspectorTab: SpanInspectorTab
    /** The scope the Errors tab opens on, when the caller named one. */
    errorsScope: ErrorScope | null
    onSelectInspectorTab: (tab: SpanInspectorTab) => void
    loading: boolean
    /** The last full-trace fetch failed (network, 4xx, 5xx) — shows a retryable error instead of the empty-trace notice. */
    loadFailed: boolean
    /** Re-fetches the open trace. Omit to hide the retry button (e.g. no clean reload path). */
    onRetry?: () => void
    /** List filters scoped the last trace lookup, so an empty trace may be filtered out rather than never sent. */
    filtersActive: boolean
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
    spans: realSpans,
    identity,
    sessionId,
    showErrorsTab,
    inspectorTab,
    errorsScope,
    onSelectInspectorTab,
    loading,
    loadFailed,
    onRetry,
    filtersActive,
    hasMoreSpans = false,
    loadingMoreSpans = false,
    onLoadMoreSpans,
    selectedSpanId,
    onSelectSpan,
    onClose,
}: TraceDrawerProps): JSX.Element | null {
    const { aiEvents, hasMoreAiEvents, aiEventsLimit, aiEventsResponseLoading, aiEventsLoadFailed } = useValues(
        traceAiEventsLogic({ traceId })
    )
    const { loadAiEvents } = useActions(traceAiEventsLogic({ traceId }))
    const anyLoadFailed = loadFailed || aiEventsLoadFailed
    const canRetry = (loadFailed && !!onRetry) || aiEventsLoadFailed
    const retryFailedLoads = (): void => {
        if (loadFailed) {
            onRetry?.()
        }
        if (aiEventsLoadFailed) {
            loadAiEvents()
        }
    }
    // The waterfall and the inspector read one list, so an AI row selects and inspects like a span.
    const spans = useMemo(() => {
        const aiEventSpans = buildAiEventSpans(aiEvents, realSpans)
        return aiEventSpans.length > 0 ? [...realSpans, ...aiEventSpans] : realSpans
    }, [realSpans, aiEvents])
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
    // Resolve the inspected span outside render churn: a resize drag re-renders this component on
    // every mousemove, and these scans are O(spans) — memoize so they only run when data/selection change.
    const rootSpan = useMemo(() => spans.find((span) => span.is_root_span) ?? spans[0] ?? null, [spans])
    const selectedSpan = useMemo(
        () => (selectedSpanId ? (spans.find((span) => span.span_id === selectedSpanId) ?? null) : null),
        [spans, selectedSpanId]
    )
    // The waterfall's "<parent span missing>" row selects an id that only appears as a parent id.
    const missingParentSpanId = useMemo(
        () =>
            selectedSpanId && !selectedSpan && spans.some((span) => span.parent_span_id === selectedSpanId)
                ? selectedSpanId
                : null,
        [spans, selectedSpanId, selectedSpan]
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
            <TraceIdentityChips identity={identity} timestamp={rootSpan?.timestamp ?? ts} />
            {/* A failed refetch only replaces the waterfall when there are no spans to fall back on. */}
            {traceId && !loading && anyLoadFailed && spans.length === 0 ? (
                <TraceLoadErrorNotice onRetry={canRetry ? retryFailedLoads : undefined} />
            ) : traceId && !loading && !aiEventsResponseLoading && spans.length === 0 ? (
                <TraceUnavailableNotice traceId={traceId} filtersActive={filtersActive} surface="drawer" />
            ) : (
                <div className="relative min-h-32 flex gap-4 items-start">
                    {(loading || (aiEventsResponseLoading && spans.length === 0)) && <SpinnerOverlay />}
                    <div className="flex-1 min-w-0">
                        {anyLoadFailed && (
                            <LemonBanner
                                type="warning"
                                className="mb-2"
                                action={canRetry ? { children: 'Try again', onClick: retryFailedLoads } : undefined}
                                data-attr="tracing-trace-load-error-banner"
                            >
                                Couldn't load the full trace. Showing the spans loaded so far.
                            </LemonBanner>
                        )}
                        <TraceAiEventsCapNotice aiEvents={aiEvents} hasMore={hasMoreAiEvents} limit={aiEventsLimit} />
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
                            inspectorWidth != null
                                ? { width: Math.max(MIN_INSPECTOR_WIDTH, inspectorWidth) }
                                : undefined
                        }
                        data-attr="tracing-span-inspector"
                    >
                        <Resizer {...inspectorResizerProps} />
                        {missingParentSpanId ? (
                            <MissingParentSpanNotice traceId={traceId ?? ''} parentSpanId={missingParentSpanId} />
                        ) : inspectedSpan ? (
                            <SpanInspector
                                span={inspectedSpan}
                                serviceColorMap={serviceColorMap}
                                traceTimestamp={rootSpan?.timestamp ?? inspectedSpan.timestamp ?? ts}
                                sessionId={sessionId}
                                showErrorsTab={showErrorsTab}
                                errorsScope={errorsScope}
                                resolving={loading}
                                tab={inspectorTab}
                                onSelectTab={onSelectInspectorTab}
                            />
                        ) : (
                            <div className="text-muted p-4">No spans in this trace</div>
                        )}
                    </div>
                </div>
            )}
        </LemonDrawer>
    )
}
