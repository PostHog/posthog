import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { pluralize } from 'lib/utils/strings'

import { SpanInspector } from 'products/tracing/frontend/components/SpanInspector/SpanInspector'
import { MissingParentSpanNotice } from 'products/tracing/frontend/components/TraceDrawer/MissingParentSpanNotice'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { TRACE_DIALOG_DATA_ATTR, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogOpenedFromLog } from './TraceDialogOpenedFromLog'
import { TraceDialogShortcuts } from './TraceDialogShortcuts'
import { TraceDialogSpanTree } from './TraceDialogSpanTree'

export function TraceDialog(): JSX.Element | null {
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
    } = useValues(traceDialogLogic)
    const { closeTraceDialog, loadTraceSpans, setInspectorTab } = useActions(traceDialogLogic)
    // The dialog sits above popovers, so the inspector's menus and drawers portal inside it instead.
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)
    const floatingContainerRef = useCallback((el: HTMLDivElement | null) => setFloatingContainer(el), [])

    if (!trace) {
        return null
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeTraceDialog}
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
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                    <TraceDialogShortcuts />
                    <LemonButton
                        type="secondary"
                        icon={<IconExternal />}
                        to={traceUrl(trace)}
                        onClick={closeTraceDialog}
                        data-attr="trace-dialog-open-in-tracing"
                    >
                        Open in Tracing
                    </LemonButton>
                </div>
            }
        >
            <FloatingContainerContext.Provider value={floatingContainer}>
                {/* The span list virtualizes, so it needs a definite height to measure against. */}
                <div className="flex flex-col gap-2 h-[65vh]">
                    <TraceDialogOpenedFromLog />
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
                        <div className="flex flex-1 flex-col items-center justify-center gap-2">
                            <span>Couldn't load this trace.</span>
                            <LemonButton type="secondary" onClick={() => loadTraceSpans(trace)}>
                                Try again
                            </LemonButton>
                        </div>
                    ) : !traceSpans || traceSpans.spans.length === 0 ? (
                        <div className="flex flex-1 items-center justify-center text-muted">
                            No spans found for this trace. Open it in Tracing to search other time ranges.
                        </div>
                    ) : (
                        <div className="@container/trace-dialog flex flex-1 min-h-0">
                            <div className="flex flex-1 min-w-0 min-h-0 flex-col @min-[56rem]/trace-dialog:flex-row">
                                <div className="flex-1 min-w-0 min-h-0">
                                    <TraceDialogSpanTree />
                                </div>
                                {(missingParentSpanId || selectedSpan) && (
                                    <div
                                        className="flex-1 min-h-0 overflow-y-auto border-t pt-4 @min-[56rem]/trace-dialog:flex-none @min-[56rem]/trace-dialog:w-2/5 @min-[56rem]/trace-dialog:border-t-0 @min-[56rem]/trace-dialog:border-l @min-[56rem]/trace-dialog:pt-0 @min-[56rem]/trace-dialog:pl-4"
                                        data-attr="trace-dialog-inspector"
                                    >
                                        {missingParentSpanId ? (
                                            <MissingParentSpanNotice
                                                traceId={trace.traceId}
                                                parentSpanId={missingParentSpanId}
                                            />
                                        ) : selectedSpan ? (
                                            <SpanInspector
                                                span={selectedSpan}
                                                serviceColorMap={serviceColorMap}
                                                traceTimestamp={summary.rootSpan?.timestamp ?? selectedSpan.timestamp}
                                                sessionId={null}
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
