import { useActions, useValues } from 'kea'
import { type CSSProperties, memo, useCallback, useMemo, useRef } from 'react'

import { LemonSegmentedButton, type LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import type { SpanTreeNode } from '~/queries/schema/schema-general'

import { SpanInspector } from 'products/tracing/frontend/components/SpanInspector/SpanInspector'
import { MissingParentSpanNotice } from 'products/tracing/frontend/components/TraceDrawer/MissingParentSpanNotice'
import type { ErrorScope } from 'products/tracing/frontend/errorCorrelation'
import { TraceCompareFlame } from 'products/tracing/frontend/TraceCompareFlame'
import type { SpanInspectorTab, TraceViewMode } from 'products/tracing/frontend/types'

import type { TraceDialogSource } from '../TraceDialog/traceDialogOpenLogic'
import { TraceDialogSpanTree } from '../TraceDialog/TraceDialogSpanTree'
import { TraceLoadMoreFooter } from './TraceLoadMoreFooter'
import { type TraceOperationsScope, traceViewLogic, type TraceViewSurface } from './traceViewLogic'

// Below this the attribute tables stop being readable, so a drag can't crush the inspector.
const MIN_INSPECTOR_WIDTH = 320

const VIEW_MODE_OPTIONS: LemonSegmentedButtonOption<TraceViewMode>[] = [
    // pinned: autocapture selects on these values, so renaming them breaks saved actions.
    // LemonSegmentedButton puts no data-attr on its root, so each option carries one.
    { value: 'waterfall', label: 'Waterfall', 'data-attr': 'tracing-trace-view-waterfall' },
    { value: 'calltree', label: 'Flame graph', 'data-attr': 'tracing-trace-view-calltree' },
]

// The call tree draws a tree of its own, so the flame gets no rows to build one from.
const NO_FLAME_ROWS: SpanTreeNode[] = []

interface TraceViewCallTreeProps {
    surface: TraceViewSurface
    /** Spans are still loading, so an empty tree is not yet a verdict. */
    resolving: boolean
    hasMoreSpans: boolean
    loadingMoreSpans: boolean
    onLoadMoreSpans?: () => void
}

/**
 * The left pane in call tree mode. Only this pane reads the call tree, so the logic builds it only in this mode.
 * Memoized because the view re-renders on every mousemove of an inspector resize drag, and on changes the pane does
 * not show, such as another inspector tab. The props stay the same then, so the flame, with a tooltip on every bar,
 * does not render again. The pane's own `useValues` renders it when the tree, the colors or the highlight change.
 */
const TraceViewCallTree = memo(function TraceViewCallTree({
    surface,
    resolving,
    hasMoreSpans,
    loadingMoreSpans,
    onLoadMoreSpans,
}: TraceViewCallTreeProps): JSX.Element {
    const { callTree, serviceColorMap, highlightedOperationKey } = useValues(traceViewLogic)
    return (
        <>
            <div className="flex-1 min-h-0 overflow-y-auto">
                {callTree.children.length === 0 ? (
                    // The surface shows its own spinner while spans load.
                    resolving ? null : (
                        <div className="text-muted text-center py-8">No spans to show in the flame graph.</div>
                    )
                ) : (
                    <TraceCompareFlame
                        tree={callTree}
                        current={NO_FLAME_ROWS}
                        previous={null}
                        loading={false}
                        sizeBy="total"
                        initialFocusKey={highlightedOperationKey}
                        serviceColorMap={serviceColorMap}
                        surface={surface}
                    />
                )}
            </div>
            {/* The call tree has no scroll trigger, so this button is the only way to load the rest of a large trace. */}
            {hasMoreSpans && <TraceLoadMoreFooter loadingMore={loadingMoreSpans} onLoadMore={onLoadMoreSpans} />}
        </>
    )
})

export interface TraceViewProps {
    traceId: string
    /** Where the view sits, for analytics. */
    surface: TraceViewSurface
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
    /** The loaded spans are not the whole trace, and the view cannot load the rest. */
    spansPartial?: boolean
    loadingMoreSpans?: boolean
    onLoadMoreSpans?: () => void
}

/**
 * The span tree, or the call tree of its operations, beside the inspector for the selected span. Mount it inside a
 * `BindLogic` for `traceViewLogic`.
 */
export function TraceView({
    traceId,
    surface,
    inspectorOpen,
    sessionId,
    showErrorsTab,
    openedFrom = null,
    openedAtUs = null,
    errorsScope = 'span',
    showFilterActions = false,
    resolving = false,
    hasMoreSpans,
    spansPartial,
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
    const {
        selectedSpan,
        missingParentSpanId,
        serviceColorMap,
        summary,
        activeInspectorTab,
        operationSpans,
        highlightedOperationKey,
        operationsTabEnabled,
        traceViewMode,
        callTreeEnabled,
    } = useValues(traceViewLogic)
    const { setInspectorTab, highlightOperation, setTraceViewMode } = useActions(traceViewLogic)
    // A click on the tab already shown still records the person's pick. Nothing on screen changes, so it passes
    // no surface and sends no event.
    const onSelectTab = useCallback(
        (tab: SpanInspectorTab, changesShownTab: boolean): void =>
            setInspectorTab(tab, changesShownTab ? surface : undefined),
        [setInspectorTab, surface]
    )
    const onHighlightOperation = useCallback(
        (operationKey: string | null, scope: TraceOperationsScope): void =>
            highlightOperation(operationKey, surface, scope),
        [highlightOperation, surface]
    )
    // Without real spans the tab would only show an empty table, so the inspector leaves it out, as it does while
    // the tab's flag is off. A resize drag re-renders this component on every mousemove, and stable values keep
    // the memoized table from rendering again for it.
    const operations = useMemo(
        () =>
            operationsTabEnabled && operationSpans.length > 0
                ? {
                      spans: operationSpans,
                      highlightedOperationKey,
                      onHighlightOperation,
                      partial: !!hasMoreSpans || !!spansPartial,
                  }
                : undefined,
        [
            operationsTabEnabled,
            operationSpans,
            highlightedOperationKey,
            onHighlightOperation,
            hasMoreSpans,
            spansPartial,
        ]
    )

    return (
        <div className="@container/trace-dialog flex flex-1 min-h-0">
            <div className="flex flex-1 min-w-0 min-h-0 flex-col @min-[56rem]/trace-dialog:flex-row">
                <div className="flex flex-col gap-2 flex-1 min-w-0 min-h-0">
                    {callTreeEnabled && (
                        <div>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={traceViewMode}
                                onChange={(mode) => setTraceViewMode(mode, surface)}
                                options={VIEW_MODE_OPTIONS}
                            />
                        </div>
                    )}
                    <div className="flex flex-col flex-1 min-h-0">
                        {traceViewMode === 'calltree' ? (
                            <TraceViewCallTree
                                surface={surface}
                                resolving={resolving}
                                hasMoreSpans={!!hasMoreSpans}
                                loadingMoreSpans={!!loadingMoreSpans}
                                onLoadMoreSpans={onLoadMoreSpans}
                            />
                        ) : (
                            <TraceDialogSpanTree
                                surface={surface}
                                openedFrom={openedFrom}
                                openedAtUs={openedAtUs}
                                hasMore={hasMoreSpans}
                                loadingMore={loadingMoreSpans}
                                onLoadMore={onLoadMoreSpans}
                                showOperationHighlight={inspectorOpen}
                            />
                        )}
                    </div>
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
                                    onSelectTab={onSelectTab}
                                    showFilterActions={showFilterActions}
                                    operations={operations}
                                />
                            ) : null}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
