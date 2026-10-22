import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconCollapse45, IconExpand45, IconExternal, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { TraceIdentityChips } from 'products/tracing/frontend/components/TraceDrawer/TraceIdentityChips'
import { TraceLoadErrorNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceLoadErrorNotice'
import { TraceUnavailableNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceUnavailableNotice'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { TraceView } from '../TraceView/TraceView'
import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TRACE_DIALOG_DATA_ATTR, TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogOpenedFromLog } from './TraceDialogOpenedFromLog'
import { TraceDialogShortcuts } from './TraceDialogShortcuts'

const TRACE_VIEW_PROPS = { id: TRACE_DIALOG_VIEW_ID }

export function TraceDialog(): JSX.Element | null {
    const {
        isOpen,
        trace,
        traceSpans,
        traceSpansLoading,
        traceSpansFailed,
        sessionErrorBadgesEnabled,
        traceIdentity,
        traceSessionId,
        inspectorOpen,
        isFullscreen,
        openedFrom,
        openedAtUs,
    } = useValues(traceDialogLogic)
    const { closeTraceDialog, loadTraceSpans, openInTracing, toggleInspector, toggleFullscreen } =
        useActions(traceDialogLogic)
    const { summary, timeline } = useValues(traceViewLogic(TRACE_VIEW_PROPS))
    // The dialog sits above popovers, so the inspector's menus and drawers, and the person popover,
    // portal inside it instead.
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)
    const floatingContainerRef = useCallback((el: HTMLDivElement | null) => setFloatingContainer(el), [])

    if (!trace) {
        return null
    }

    return (
        <LemonModal
            isOpen={isOpen}
            // The close button hands onClose its click event, which must not land in the reason argument.
            onClose={() => closeTraceDialog('dismissed')}
            title={<span translate="no">{summary.rootSpan?.name ?? 'Trace'}</span>}
            description={
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs" translate="no">
                        {trace.traceId}
                    </span>
                    {traceSpans && traceSpans.spans.length > 0 && (
                        <>
                            <LemonTag>{formatDuration(timeline.durationUs * 1_000)}</LemonTag>
                            <LemonTag>
                                {pluralize(summary.spanCount, 'span')} · {pluralize(summary.serviceCount, 'service')}
                            </LemonTag>
                            {summary.errorCount > 0 && (
                                <LemonTag type="danger">{pluralize(summary.errorCount, 'error')}</LemonTag>
                            )}
                        </>
                    )}
                </div>
            }
            forceAbovePopovers
            data-attr={TRACE_DIALOG_DATA_ATTR}
            width="90vw"
            maxWidth={1600}
            fullScreen={isFullscreen}
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                    <TraceDialogShortcuts />
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            icon={inspectorOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
                            tooltip={inspectorOpen ? 'Hide span details' : 'Show span details'}
                            onClick={toggleInspector}
                            data-attr="trace-dialog-toggle-inspector"
                        />
                        <LemonButton
                            type="secondary"
                            icon={isFullscreen ? <IconCollapse45 /> : <IconExpand45 />}
                            tooltip={isFullscreen ? 'Exit full screen' : 'Full screen'}
                            onClick={toggleFullscreen}
                            data-attr="trace-dialog-toggle-fullscreen"
                        />
                        <LemonButton
                            type="secondary"
                            icon={<IconExternal />}
                            to={traceUrl(trace)}
                            onClick={openInTracing}
                            data-attr="trace-dialog-open-in-tracing"
                        >
                            Open in Tracing
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <FloatingContainerContext.Provider value={floatingContainer}>
                {/* The span list virtualizes, so it needs a definite height to measure against. Full screen
                    leaves room for the dialog's header and footer. */}
                <div className={cn('flex flex-col gap-2', isFullscreen ? 'h-[calc(100vh-12rem)]' : 'h-[65vh]')}>
                    <TraceDialogOpenedFromLog />
                    <TraceIdentityChips
                        identity={traceIdentity}
                        timestamp={summary.rootSpan?.timestamp ?? trace.ts ?? null}
                        // The player modal stacks below this dialog, so the recording opens in a new tab.
                        openRecordingIn={RecordingPlayerType.NewTab}
                    />
                    {traceSpans?.truncated && (
                        <LemonBanner type="info">
                            Showing the first {summary.spanCount.toLocaleString()} spans. Open this trace in Tracing to
                            see all of them.
                        </LemonBanner>
                    )}
                    {traceSpansLoading ? (
                        <div className="flex flex-1 items-center justify-center">
                            <Spinner className="text-2xl" />
                        </div>
                    ) : traceSpansFailed ? (
                        <TraceLoadErrorNotice onRetry={() => loadTraceSpans(trace)} />
                    ) : !traceSpans || traceSpans.spans.length === 0 ? (
                        // The dialog has no filters, and Open in Tracing below covers spans outside its time window.
                        <TraceUnavailableNotice traceId={trace.traceId} filtersActive={false} surface="trace_dialog" />
                    ) : (
                        <BindLogic logic={traceViewLogic} props={TRACE_VIEW_PROPS}>
                            <TraceView
                                traceId={trace.traceId}
                                inspectorOpen={inspectorOpen}
                                sessionId={traceSessionId}
                                showErrorsTab={sessionErrorBadgesEnabled}
                                openedFrom={openedFrom}
                                openedAtUs={openedAtUs}
                            />
                        </BindLogic>
                    )}
                </div>
                <div ref={floatingContainerRef} />
            </FloatingContainerContext.Provider>
        </LemonModal>
    )
}
