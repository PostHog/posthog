import { BindLogic, useActions, useValues } from 'kea'

import { IconExternal, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { traceUrl, type TraceLinkParams } from 'lib/components/ViewTraceButton/traceUrl'
import { pluralize } from 'lib/utils/strings'

import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { TraceLoadErrorNotice } from '../TraceDrawer/TraceLoadErrorNotice'
import { TraceUnavailableNotice } from '../TraceDrawer/TraceUnavailableNotice'
import { TraceView } from '../TraceView/TraceView'
import { type TraceViewSurface, traceViewLogic } from '../TraceView/traceViewLogic'
import { traceEmbedLogic } from './traceEmbedLogic'

export interface TraceEmbedProps {
    viewId: string
    trace: TraceLinkParams
    surface: TraceViewSurface
    'data-attr': string
}

export function TraceEmbed({ viewId, trace, surface, 'data-attr': dataAttr }: TraceEmbedProps): JSX.Element {
    const logic = traceEmbedLogic({ viewId, trace, surface })
    const { traceSpans, traceSpansLoading, traceSpansFailed, inspectorOpen } = useValues(logic)
    const { loadTraceSpans, toggleInspector, openInTracing } = useActions(logic)
    const { summary, timeline } = useValues(traceViewLogic({ id: viewId }))

    return (
        <BindLogic logic={traceViewLogic} props={{ id: viewId }}>
            <div className="flex min-h-0 flex-1 flex-col gap-2 p-2" data-attr={dataAttr}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1">
                        {summary.spanCount > 0 && (
                            <>
                                <LemonTag>{formatDuration(timeline.durationUs * 1_000)}</LemonTag>
                                <LemonTag>
                                    {pluralize(summary.spanCount, 'span')} ·{' '}
                                    {pluralize(summary.serviceCount, 'service')}
                                </LemonTag>
                                {summary.errorCount > 0 && (
                                    <LemonTag type="danger">{pluralize(summary.errorCount, 'error')}</LemonTag>
                                )}
                            </>
                        )}
                    </div>
                    <div className="flex items-center gap-1">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={inspectorOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
                            tooltip={inspectorOpen ? 'Hide span details' : 'Show span details'}
                            onClick={toggleInspector}
                            data-attr={`${dataAttr}-toggle-inspector`}
                        />
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconExternal />}
                            to={traceUrl(trace)}
                            onClick={openInTracing}
                            data-attr={`${dataAttr}-open-in-tracing`}
                        >
                            Open in Tracing
                        </LemonButton>
                    </div>
                </div>
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
                    <TraceLoadErrorNotice onRetry={() => loadTraceSpans()} />
                ) : !traceSpans || traceSpans.spans.length === 0 ? (
                    <TraceUnavailableNotice traceId={trace.traceId} filtersActive={false} surface={surface} />
                ) : (
                    <TraceView
                        traceId={trace.traceId}
                        surface={surface}
                        inspectorOpen={inspectorOpen}
                        sessionId={null}
                        showErrorsTab={false}
                        spansPartial={traceSpans.truncated}
                    />
                )}
            </div>
        </BindLogic>
    )
}
