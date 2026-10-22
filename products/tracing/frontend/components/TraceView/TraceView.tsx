import { useActions, useValues } from 'kea'
import { type CSSProperties, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { SpanInspector } from 'products/tracing/frontend/components/SpanInspector/SpanInspector'
import { MissingParentSpanNotice } from 'products/tracing/frontend/components/TraceDrawer/MissingParentSpanNotice'
import type { ErrorScope } from 'products/tracing/frontend/errorCorrelation'

import type { TraceDialogSource } from '../TraceDialog/traceDialogLogic'
import { TraceDialogSpanTree } from '../TraceDialog/TraceDialogSpanTree'
import { traceViewLogic } from './traceViewLogic'

// Below this the attribute tables stop being readable, so a drag can't crush the inspector.
const MIN_INSPECTOR_WIDTH = 320

export interface TraceViewProps {
    traceId: string
    inspectorOpen: boolean
    sessionId: string | null
    showErrorsTab: boolean
    openedFrom?: TraceDialogSource | null
    openedAtUs?: number | null
    errorsScope?: ErrorScope | null
    /** The attribute filter buttons narrow a span list, so show them only where one sits behind the view. */
    showFilterActions?: boolean
    /** Spans are still loading, so the inspector holds off on what it reads from them. */
    resolving?: boolean
    hasMoreSpans?: boolean
    loadingMoreSpans?: boolean
    onLoadMoreSpans?: () => void
}

/** The span tree beside the inspector for the selected span. Mount it inside a `BindLogic` for `traceViewLogic`. */
export function TraceView({
    traceId,
    inspectorOpen,
    sessionId,
    showErrorsTab,
    openedFrom = null,
    openedAtUs = null,
    errorsScope = 'span',
    showFilterActions = false,
    resolving = false,
    hasMoreSpans,
    loadingMoreSpans,
    onLoadMoreSpans,
}: TraceViewProps): JSX.Element {
    const inspectorRef = useRef<HTMLDivElement>(null)
    const inspectorResizerProps: ResizerLogicProps = {
        // Pinned: the persisted inspector width lives under this key.
        logicKey: 'trace-dialog-span-inspector',
        placement: 'left',
        containerRef: inspectorRef,
        persistent: true,
    }
    const { desiredSize: inspectorWidth } = useValues(resizerLogic(inspectorResizerProps))
    const { selectedSpan, missingParentSpanId, serviceColorMap, summary, activeInspectorTab } =
        useValues(traceViewLogic)
    const { setInspectorTab } = useActions(traceViewLogic)

    return (
        <div className="@container/trace-dialog flex flex-1 min-h-0">
            <div className="flex flex-1 min-w-0 min-h-0 flex-col @min-[56rem]/trace-dialog:flex-row">
                <div className="flex-1 min-w-0 min-h-0">
                    <TraceDialogSpanTree
                        openedFrom={openedFrom}
                        openedAtUs={openedAtUs}
                        hasMore={hasMoreSpans}
                        loadingMore={loadingMoreSpans}
                        onLoadMore={onLoadMoreSpans}
                    />
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
                        <Resizer {...inspectorResizerProps} className="hidden @min-[56rem]/trace-dialog:block" />
                        {/* Scrolls inside the sized box, so the drag handle stays put. */}
                        <div className="h-full overflow-y-auto @min-[56rem]/trace-dialog:pl-4">
                            {missingParentSpanId ? (
                                <MissingParentSpanNotice traceId={traceId} parentSpanId={missingParentSpanId} />
                            ) : selectedSpan ? (
                                <SpanInspector
                                    span={selectedSpan}
                                    serviceColorMap={serviceColorMap}
                                    traceTimestamp={summary.rootSpan?.timestamp ?? selectedSpan.timestamp}
                                    sessionId={sessionId}
                                    showErrorsTab={showErrorsTab}
                                    errorsScope={errorsScope}
                                    resolving={resolving}
                                    tab={activeInspectorTab}
                                    onSelectTab={setInspectorTab}
                                    showFilterActions={showFilterActions}
                                />
                            ) : null}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
