import { useActions, useValues } from 'kea'
import { useLayoutEffect, useMemo } from 'react'

import { LemonBanner, LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { buildAiEventSpans } from '../../aiEventSpans'
import type { ErrorScope } from '../../errorCorrelation'
import { useKeepMountedWhileOpen } from '../../hooks/useKeepMountedWhileOpen'
import type { TraceIdentity } from '../../traceIdentity'
import { absoluteTraceUrl } from '../../traceLinks'
import { TRACE_DRAWER_DATA_ATTR } from '../../tracingViewerLogic'
import type { Span } from '../../types'
import { TraceView } from '../TraceView/TraceView'
import { TraceViewDrawer } from '../TraceView/TraceViewDrawer'
import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TraceViewShortcuts } from '../TraceView/TraceViewShortcuts'
import { TraceAiEventsCapNotice } from './TraceAiEventsCapNotice'
import { traceAiEventsLogic } from './traceAiEventsLogic'
import { TraceIdentityChips } from './TraceIdentityChips'
import { TraceLoadErrorNotice } from './TraceLoadErrorNotice'
import { TraceUnavailableNotice } from './TraceUnavailableNotice'

export interface TraceDrawerProps {
    viewId: string
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
    /** The scope the Errors tab opens on, when the caller named one. */
    errorsScope: ErrorScope | null
    inspectorOpen: boolean
    onToggleInspector: () => void
    isFullscreen: boolean
    onToggleFullscreen: () => void
    loading: boolean
    /** The last full-trace fetch failed (network, 4xx, 5xx) — shows a retryable error instead of the empty-trace notice. */
    loadFailed: boolean
    /** Re-fetches the open trace. Omit to hide the retry button (e.g. no clean reload path). */
    onRetry?: () => void
    /** List filters scoped the last trace lookup, so an empty trace may be filtered out rather than never sent. */
    filtersActive: boolean
    /** The open trace has more spans than the loaded pages — drives the span tree's infinite scroll. */
    hasMoreSpans?: boolean
    /** A next page of spans is being fetched (shows a bottom spinner without the full overlay). */
    loadingMoreSpans?: boolean
    onLoadMoreSpans?: () => void
    onClose: () => void
}

// Master-detail split: the span tree on the left drives the span inspector on the right — the same
// list→detail relationship the span list has with this drawer, one level down. Tabs live *inside*
// the inspector (Attributes / Logs), not at the drawer level — so the tree stays visible while
// you read a span's attributes or its correlated logs.
export function TraceDrawer({
    viewId,
    isOpen,
    traceId,
    ts,
    spans: realSpans,
    identity,
    sessionId,
    showErrorsTab,
    errorsScope,
    inspectorOpen,
    onToggleInspector,
    isFullscreen,
    onToggleFullscreen,
    loading,
    loadFailed,
    onRetry,
    filtersActive,
    hasMoreSpans = false,
    loadingMoreSpans = false,
    onLoadMoreSpans,
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
    // The tree and the inspector read one list, so an AI row selects and inspects like a span.
    const spans = useMemo(() => {
        const aiEventSpans = buildAiEventSpans(aiEvents, realSpans)
        return aiEventSpans.length > 0 ? [...realSpans, ...aiEventSpans] : realSpans
    }, [realSpans, aiEvents])

    const view = traceViewLogic({ id: viewId })
    const { spans: viewSpans, summary, selectedSpanId } = useValues(view)
    const { setSpans } = useActions(view)
    // The AI rows merge here rather than in a logic, so this hands the merged list to the view. Opening a
    // trace clears the view's spans, and comparing against them puts the list back even when it is unchanged.
    // A layout effect, so the cleared tree never paints.
    useLayoutEffect(() => {
        if (viewSpans !== spans) {
            setSpans(spans)
        }
    }, [spans, viewSpans, setSpans])

    // Gate mounting so a closed drawer holds no react-modal portal (and its listener surface).
    const shouldRender = useKeepMountedWhileOpen(isOpen)
    if (!shouldRender) {
        return null
    }

    return (
        <TraceViewDrawer
            viewId={viewId}
            traceId={traceId}
            isOpen={isOpen}
            onClose={onClose}
            inspectorOpen={inspectorOpen}
            onToggleInspector={onToggleInspector}
            isFullscreen={isFullscreen}
            onToggleFullscreen={onToggleFullscreen}
            shortcuts={<TraceViewShortcuts closeLabel="Close" />}
            headerActions={
                <LemonButton
                    size="xsmall"
                    icon={<IconLink />}
                    tooltip="Copy link to this trace"
                    data-attr="tracing-drawer-copy-link"
                    onClick={() =>
                        traceId &&
                        void copyToClipboard(absoluteTraceUrl({ traceId, spanId: selectedSpanId, ts }), 'trace link')
                    }
                />
            }
            data-attr={TRACE_DRAWER_DATA_ATTR}
        >
            <TraceIdentityChips identity={identity} timestamp={summary.rootSpan?.timestamp ?? ts} />
            {/* A failed refetch only replaces the tree when there are no spans to fall back on. */}
            {traceId && !loading && anyLoadFailed && spans.length === 0 ? (
                <TraceLoadErrorNotice onRetry={canRetry ? retryFailedLoads : undefined} />
            ) : traceId && !loading && !aiEventsResponseLoading && spans.length === 0 ? (
                <TraceUnavailableNotice traceId={traceId} filtersActive={filtersActive} surface="drawer" />
            ) : (
                <div className="relative flex flex-col flex-1 min-h-0 gap-2">
                    {(loading || (aiEventsResponseLoading && spans.length === 0)) && <SpinnerOverlay />}
                    {anyLoadFailed && (
                        <LemonBanner
                            type="warning"
                            action={canRetry ? { children: 'Try again', onClick: retryFailedLoads } : undefined}
                            data-attr="tracing-trace-load-error-banner"
                        >
                            Couldn't load the full trace. Showing the spans loaded so far.
                        </LemonBanner>
                    )}
                    <TraceAiEventsCapNotice aiEvents={aiEvents} hasMore={hasMoreAiEvents} limit={aiEventsLimit} />
                    <TraceView
                        traceId={traceId ?? ''}
                        inspectorOpen={inspectorOpen}
                        sessionId={sessionId}
                        showErrorsTab={showErrorsTab}
                        errorsScope={errorsScope}
                        showFilterActions
                        resolving={loading}
                        hasMoreSpans={hasMoreSpans}
                        loadingMoreSpans={loadingMoreSpans}
                        onLoadMoreSpans={onLoadMoreSpans}
                    />
                </div>
            )}
        </TraceViewDrawer>
    )
}
