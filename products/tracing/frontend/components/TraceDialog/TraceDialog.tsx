import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { pluralize } from 'lib/utils/strings'

import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceDialogLogic } from './traceDialogLogic'
import { TraceDialogSpanTree } from './TraceDialogSpanTree'

export function TraceDialog(): JSX.Element | null {
    const { isOpen, trace, traceSpans, traceSpansLoading, traceSpansFailed, summary, timeline } =
        useValues(traceDialogLogic)
    const { closeTraceDialog, loadTraceSpans } = useActions(traceDialogLogic)

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
            width="90vw"
            maxWidth={1600}
            footer={
                <LemonButton
                    type="secondary"
                    icon={<IconExternal />}
                    to={traceUrl(trace)}
                    onClick={closeTraceDialog}
                    data-attr="trace-dialog-open-in-tracing"
                >
                    Open in Tracing
                </LemonButton>
            }
        >
            {/* The span list virtualizes, so it needs a definite height to measure against. */}
            <div className="flex flex-col gap-2 h-[65vh]">
                {traceSpans?.truncated && (
                    <LemonBanner type="info">
                        Showing the first {summary.spanCount.toLocaleString()} spans. Open this trace in Tracing to see
                        all of them.
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
                    <div className="flex-1 min-h-0">
                        <TraceDialogSpanTree />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
