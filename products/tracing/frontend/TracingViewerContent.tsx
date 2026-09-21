import { useActions, useValues } from 'kea'

import { LemonDivider, LemonModal, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { ComparisonBar } from './components/Comparison/ComparisonBar'
import { FacetRail } from './components/FacetRail/FacetRail'
import { TraceDrawer } from './components/TraceDrawer/TraceDrawer'
import { VirtualizedSpanList } from './components/VirtualizedSpanList/VirtualizedSpanList'
import { TRACING_DISPLAY_TIMEZONE } from './dateFormats'
import { OperationsTable } from './OperationsTable'
import { TraceCompareFlame } from './TraceCompareFlame'
import { TraceCompareTable } from './TraceCompareTable'
import { tracingConfigLogic } from './tracingConfigLogic'
import { tracingDataLogic } from './tracingDataLogic'
import { TracingDisplayBar } from './TracingDisplayBar'
import { TracingFilterBar } from './TracingFilterBar'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { TracingSparkline } from './TracingSparkline'
import type { TracingViewerProps } from './TracingViewer'
import { tracingViewerLogic } from './tracingViewerLogic'
import type { Span } from './types'

const TRACING_DOCS_URL = 'https://posthog.com/docs/tracing'

export function TracingViewerContent({
    id,
    showSavedViewsButton,
    onOperationClick,
}: Pick<TracingViewerProps, 'id' | 'showSavedViewsButton' | 'onOperationClick'>): JSX.Element {
    const {
        listRows,
        spansLoading,
        sparklineData,
        sparklineLoading,
        traceSpansLoadingMore,
        aggregation,
        aggregationLoading,
        spanTree,
        spanTreeLoading,
        hasMoreToLoad,
        visibleRowDateRange,
        durationHistogramData,
        durationHistogramLoading,
        visibleRowDurationRange,
        isDurationMode,
        latencyHeatmapData,
        latencyHeatmapLoading,
        showHeatmap,
    } = useValues(tracingDataLogic)
    const {
        isTraceOpen,
        selectedTraceId,
        selectedSpanId,
        selectedTraceTs,
        openTraceSpans,
        traceIdentity,
        isLoadingFullTrace,
        canLoadMoreTraceSpans,
        compareFlameSpanName,
        activeTracingTab,
    } = useValues(tracingViewerLogic)
    const { filters, currentWindowMs, previousWindowMs, compareActive } = useValues(tracingFiltersLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openTrace, closeTrace, selectSpan, openCompareFlame, closeCompareFlame } = useActions(tracingViewerLogic)
    const { setDateRange, updateComparisonWindows, setSort, setChartType } = useActions(tracingFiltersLogic)
    const { fetchNextPage, loadMoreTraceSpans, setVisibleRowRange, applyHeatmapBrush } = useActions(tracingDataLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { facetRailCollapsed } = useValues(tracingConfigLogic)
    const operationsViewEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_OPERATIONS_VIEW]
    const facetRailEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_FACET_RAIL]
    const heatmapEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_LATENCY_HEATMAP]

    // Resolved aggregation window (ms) — turns span counts into a request rate.
    // Use sparklineWindowMs which correctly resolves relative date strings (e.g. '-1h').
    const { sparklineWindowMs, utcDateRange } = useValues(tracingFiltersLogic)
    const operationsWindowMs = sparklineWindowMs.endMs - sparklineWindowMs.startMs

    const onDocsLinkClick = (): void => {
        addProductIntent({
            product_type: ProductKey.TRACING,
            intent_context: ProductIntentContext.TRACING_DOCS_VIEWED,
        })
    }

    // Anchor the overlay's coordinate space to the *fetched* sparkline data so overlay
    // drags never shift the canvas underfoot. The sparkline only refetches when dateRange
    // changes (via the DateFilter), never via overlay interaction. Only the 'custom' preset
    // shows draggable windows — named presets compare the full range, whose baseline window
    // sits outside the visible sparkline anyway.
    const sparklineFirstMs = sparklineData.dates.length > 0 ? new Date(sparklineData.dates[0]).valueOf() : null
    const sparklineLastMs =
        sparklineData.dates.length > 0 ? new Date(sparklineData.dates[sparklineData.dates.length - 1]).valueOf() : null
    const compareConfig =
        filters.comparison?.mode === 'time' &&
        filters.comparison.preset === 'custom' &&
        sparklineFirstMs !== null &&
        sparklineLastMs !== null
            ? {
                  fullStartMs: sparklineFirstMs,
                  fullEndMs: sparklineLastMs,
                  currentWindow: currentWindowMs,
                  previousWindow: previousWindowMs,
                  onChange: updateComparisonWindows,
              }
            : undefined

    return (
        <div className="flex flex-col flex-1 min-h-0 gap-y-4">
            <>
                <TracingFilterBar id={id} showSavedViewsButton={showSavedViewsButton} />
                <LemonDivider />
                <TracingSparkline
                    sparklineData={sparklineData}
                    sparklineLoading={sparklineLoading || (isDurationMode && !showHeatmap && durationHistogramLoading)}
                    onDateRangeChange={setDateRange}
                    displayTimezone={TRACING_DISPLAY_TIMEZONE}
                    currentDateTo={utcDateRange.date_to}
                    compare={compareConfig}
                    compareActive={compareActive}
                    visibleRowDateRange={visibleRowDateRange}
                    durationHistogram={isDurationMode && !showHeatmap ? durationHistogramData : null}
                    visibleRowDurationRange={visibleRowDurationRange}
                    chartType={filters.chartType}
                    onChartTypeChange={heatmapEnabled ? setChartType : undefined}
                    latencyHeatmap={showHeatmap ? latencyHeatmapData : null}
                    latencyHeatmapLoading={latencyHeatmapLoading}
                    onHeatmapBrush={applyHeatmapBrush}
                    heatmapDisabledReason={
                        compareActive ? 'The heatmap is unavailable while comparing time windows' : null
                    }
                />
                <div className="flex flex-row gap-2 flex-1 min-h-0">
                    {facetRailEnabled && !facetRailCollapsed && <FacetRail id={id} />}
                    <div className="flex flex-col gap-2 flex-1 min-w-0 min-h-0">
                        <TracingDisplayBar />
                        {compareActive && (!operationsViewEnabled || activeTracingTab !== 'operations') && (
                            <ComparisonBar />
                        )}
                        {operationsViewEnabled && activeTracingTab === 'operations' ? (
                            <OperationsTable
                                rows={aggregation.current}
                                loading={aggregationLoading}
                                windowMs={operationsWindowMs}
                                onRowClick={
                                    onOperationClick ? (row) => onOperationClick(row, filters.dateRange) : undefined
                                }
                            />
                        ) : compareActive ? (
                            <TraceCompareTable
                                current={aggregation.current}
                                previous={aggregation.previous}
                                loading={aggregationLoading}
                                onRowClick={(row) => openCompareFlame(row.name, row.service_name)}
                            />
                        ) : (
                            <VirtualizedSpanList
                                dataSource={listRows}
                                loading={spansLoading}
                                hasMoreToLoad={hasMoreToLoad}
                                onLoadMore={fetchNextPage}
                                onVisibleRowRangeChange={setVisibleRowRange}
                                orderBy={filters.orderBy}
                                orderDirection={filters.orderDirection}
                                onSort={(column) =>
                                    // Click an active column to flip direction; a new column starts at DESC.
                                    setSort(
                                        column,
                                        column === filters.orderBy && filters.orderDirection === 'DESC' ? 'ASC' : 'DESC'
                                    )
                                }
                                emptyState={
                                    <div className="flex flex-col items-center gap-1">
                                        <span>No spans found</span>
                                        <Link to={TRACING_DOCS_URL} onClick={onDocsLinkClick} target="_blank">
                                            Learn how to send traces
                                        </Link>
                                    </div>
                                }
                                onRowClick={(span: Span) => {
                                    // Clicking a row leaves the scrollable <main tabIndex="0"> as the active
                                    // element; react-modal then scrolls it back into view when restoring focus
                                    // on close. Blur so the restore target is <body>, which doesn't scroll.
                                    ;(document.activeElement as HTMLElement | null)?.blur?.()
                                    // Anchor the waterfall on the clicked span — in Spans mode this is often a
                                    // child span, so without spanId the drawer would open unfocused at the root.
                                    openTrace(span.trace_id, { spanId: span.span_id, ts: span.timestamp })
                                }}
                            />
                        )}
                    </div>
                </div>
            </>
            <TraceDrawer
                isOpen={isTraceOpen}
                traceId={selectedTraceId}
                ts={selectedTraceTs}
                spans={openTraceSpans}
                identity={traceIdentity}
                loading={isLoadingFullTrace}
                hasMoreSpans={canLoadMoreTraceSpans}
                loadingMoreSpans={traceSpansLoadingMore}
                onLoadMoreSpans={loadMoreTraceSpans}
                selectedSpanId={selectedSpanId}
                onSelectSpan={selectSpan}
                onClose={closeTrace}
            />
            <LemonModal
                title={`Call tree diff: ${compareFlameSpanName ?? ''}`}
                isOpen={compareFlameSpanName !== null}
                onClose={closeCompareFlame}
                width="90vw"
            >
                <TraceCompareFlame
                    current={spanTree.current}
                    previous={spanTree.previous}
                    loading={spanTreeLoading}
                    initialSpanName={compareFlameSpanName}
                />
            </LemonModal>
        </div>
    )
}
