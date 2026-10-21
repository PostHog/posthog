import { useActions, useValues } from 'kea'
import { type CSSProperties, useCallback, useRef, useState } from 'react'

import { IconCollapse45, IconExpand45, IconExternal, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { SpanInspector } from 'products/tracing/frontend/components/SpanInspector/SpanInspector'
import { MissingParentSpanNotice } from 'products/tracing/frontend/components/TraceDrawer/MissingParentSpanNotice'
import { TraceIdentityChips } from 'products/tracing/frontend/components/TraceDrawer/TraceIdentityChips'
import { TraceLoadErrorNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceLoadErrorNotice'
import { TraceUnavailableNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceUnavailableNotice'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { TRACE_DIALOG_DATA_ATTR, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogOpenedFromLog } from './TraceDialogOpenedFromLog'
import { TraceDialogShortcuts } from './TraceDialogShortcuts'
import { TraceDialogSpanTree } from './TraceDialogSpanTree'

// Below this the attribute tables stop being readable, so a drag can't crush the inspector.
const MIN_INSPECTOR_WIDTH = 320

export function TraceDialog(): JSX.Element | null {
    // Persisted under its own key: the dialog is wider than the drawer, so a split the person
    // picked in one would be wrong in the other.
    const inspectorRef = useRef<HTMLDivElement>(null)
    const inspectorResizerProps: ResizerLogicProps = {
        logicKey: 'trace-dialog-span-inspector',
        placement: 'left',
        containerRef: inspectorRef,
        persistent: true,
    }
    const { desiredSize: inspectorWidth } = useValues(resizerLogic(inspectorResizerProps))
    const {
        isOpen,
        trace,
        traceSpans,
        traceSpansLoading,
        traceSpansFailed,
        summary,
        timeline,
        selectedSpan,
        missingParentSpanId,
        serviceColorMap,
        activeInspectorTab,
        sessionErrorBadgesEnabled,
        traceIdentity,
        traceSessionId,
        inspectorOpen,
        isFullscreen,
    } = useValues(traceDialogLogic)
    const { closeTraceDialog, loadTraceSpans, setInspectorTab, openInTracing, toggleInspector, toggleFullscreen } =
        useActions(traceDialogLogic)
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
                        <div className="@container/trace-dialog flex flex-1 min-h-0">
                            <div className="flex flex-1 min-w-0 min-h-0 flex-col @min-[56rem]/trace-dialog:flex-row">
                                <div className="flex-1 min-w-0 min-h-0">
                                    <TraceDialogSpanTree />
                                </div>
                                {inspectorOpen && (missingParentSpanId || selectedSpan) && (
                                    <div
                                        ref={inspectorRef}
                                        // Half the body at most side by side, so the span tree keeps room for its timeline bars.
                                        className="relative flex-1 min-h-0 border-t pt-4 @min-[56rem]/trace-dialog:flex-none @min-[56rem]/trace-dialog:w-(--trace-dialog-inspector-width) @min-[56rem]/trace-dialog:max-w-1/2 @min-[56rem]/trace-dialog:border-t-0 @min-[56rem]/trace-dialog:border-l @min-[56rem]/trace-dialog:pt-0"
                                        // The dragged width applies only side by side; stacked, the inspector is full width.
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={
                                            {
                                                '--trace-dialog-inspector-width':
                                                    inspectorWidth != null
                                                        ? `${Math.max(MIN_INSPECTOR_WIDTH, inspectorWidth)}px`
                                                        : '40%',
                                            } as CSSProperties
                                        }
                                        data-attr="trace-dialog-inspector"
                                    >
                                        <Resizer
                                            {...inspectorResizerProps}
                                            className="hidden @min-[56rem]/trace-dialog:block"
                                        />
                                        {/* Scrolls inside the sized box, so the drag handle stays put. */}
                                        <div className="h-full overflow-y-auto @min-[56rem]/trace-dialog:pl-4">
                                            {missingParentSpanId ? (
                                                <MissingParentSpanNotice
                                                    traceId={trace.traceId}
                                                    parentSpanId={missingParentSpanId}
                                                />
                                            ) : selectedSpan ? (
                                                <SpanInspector
                                                    span={selectedSpan}
                                                    serviceColorMap={serviceColorMap}
                                                    traceTimestamp={
                                                        summary.rootSpan?.timestamp ?? selectedSpan.timestamp
                                                    }
                                                    sessionId={traceSessionId}
                                                    showErrorsTab={sessionErrorBadgesEnabled}
                                                    errorsScope="span"
                                                    resolving={false}
                                                    tab={activeInspectorTab}
                                                    onSelectTab={setInspectorTab}
                                                    // The dialog has no span list for an attribute filter to narrow.
                                                    showFilterActions={false}
                                                />
                                            ) : null}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
                <div ref={floatingContainerRef} />
            </FloatingContainerContext.Provider>
        </LemonModal>
    )
}
