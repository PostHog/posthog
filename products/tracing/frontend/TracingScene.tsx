import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { FacetRail } from './components/FacetRail/FacetRail'
import { TracingSetupPrompt } from './components/SetupPrompt/SetupPrompt'
import { TraceDrawer } from './components/TraceDrawer/TraceDrawer'
import { VirtualizedSpanList } from './components/VirtualizedSpanList/VirtualizedSpanList'
import { OperationsTable } from './OperationsTable'
import { TraceCompareFlame } from './TraceCompareFlame'
import { TraceCompareTable } from './TraceCompareTable'
import { tracingConfigLogic } from './tracingConfigLogic'
import { tracingDataLogic } from './tracingDataLogic'
import { TracingDisplayBar } from './TracingDisplayBar'
import { TracingFilterBar } from './TracingFilterBar'
import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingSceneLogic } from './tracingSceneLogic'
import { TracingSparkline } from './TracingSparkline'
import type { Span } from './types'

const TRACING_FEEDBACK_SURVEY_ID = '019e6a26-4943-0000-24a0-dc46310f6b7c'
const TRACING_DOCS_URL = 'https://posthog.com/docs/tracing'

export const scene: SceneExport = {
    component: TracingScene,
    logic: tracingSceneLogic,
    productKey: ProductKey.TRACING,
}

export default function TracingScene(): JSX.Element {
    const sceneLogic = tracingSceneLogic()
    // Keep filters + data logic alive across React unmounts by attaching them to the scene root.
    useAttachedLogic(tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID }), sceneLogic)
    useAttachedLogic(tracingDataLogic({ id: TRACING_SCENE_VIEWER_ID }), sceneLogic)

    // Bind the scene's keyed instances so nested components (filter bar, sparkline, ...)
    // resolve them from context — the same components work inside an embedded viewer
    // bound to a different id.
    return (
        <BindLogic logic={tracingFiltersLogic} props={{ id: TRACING_SCENE_VIEWER_ID }}>
            <BindLogic logic={tracingDataLogic} props={{ id: TRACING_SCENE_VIEWER_ID }}>
                <TracingSceneContents />
            </BindLogic>
        </BindLogic>
    )
}

function TracingSceneContents(): JSX.Element {
    const {
        listRows,
        spansLoading,
        isTraceOpen,
        selectedTraceId,
        selectedSpanId,
        selectedTraceTs,
        sparklineData,
        sparklineLoading,
        openTraceSpans,
        isLoadingFullTrace,
        canLoadMoreTraceSpans,
        traceSpansLoadingMore,
        aggregation,
        aggregationLoading,
        filters,
        currentWindowMs,
        previousWindowMs,
        spanTree,
        spanTreeLoading,
        compareFlameSpanName,
        hasMoreToLoad,
        visibleRowDateRange,
        durationHistogramData,
        durationHistogramLoading,
        visibleRowDurationRange,
        isDurationMode,
        activeTracingTab,
    } = useValues(tracingSceneLogic())
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        openTrace,
        closeTrace,
        selectSpan,
        setDateRange,
        setOverlayWindows,
        openCompareFlame,
        closeCompareFlame,
        fetchNextPage,
        loadMoreTraceSpans,
        setVisibleRowRange,
        setSort,
    } = useActions(tracingSceneLogic())
    const { addProductIntent } = useActions(teamLogic)
    const { facetRailCollapsed } = useValues(tracingConfigLogic)
    const compareMode = filters.compareMode
    const operationsViewEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_OPERATIONS_VIEW]
    const facetRailEnabled = !!featureFlags[FEATURE_FLAGS.TRACING_FACET_RAIL]

    // Resolved aggregation window (ms) — turns span counts into a request rate.
    // Use sparklineWindowMs which correctly resolves relative date strings (e.g. '-1h').
    const { sparklineWindowMs } = useValues(tracingFiltersLogic)
    const operationsWindowMs = sparklineWindowMs.endMs - sparklineWindowMs.startMs

    const onDocsLinkClick = (): void => {
        addProductIntent({
            product_type: ProductKey.TRACING,
            intent_context: ProductIntentContext.TRACING_DOCS_VIEWED,
        })
    }

    const onFeedbackClick = (): void => {
        posthog.displaySurvey(TRACING_FEEDBACK_SURVEY_ID)
    }

    // Anchor the overlay's coordinate space to the *fetched* sparkline data so overlay
    // drags never shift the canvas underfoot. The sparkline only refetches when dateRange
    // changes (via the DateFilter), never via overlay interaction.
    const sparklineFirstMs = sparklineData.dates.length > 0 ? new Date(sparklineData.dates[0]).valueOf() : null
    const sparklineLastMs =
        sparklineData.dates.length > 0 ? new Date(sparklineData.dates[sparklineData.dates.length - 1]).valueOf() : null
    const compareConfig =
        compareMode && sparklineFirstMs !== null && sparklineLastMs !== null
            ? {
                  fullStartMs: sparklineFirstMs,
                  fullEndMs: sparklineLastMs,
                  currentWindow: currentWindowMs,
                  previousWindow: previousWindowMs,
                  onChange: setOverlayWindows,
              }
            : undefined

    return (
        <SceneContent className="h-[calc(var(--scene-layout-rect-height,_100vh)_-_1rem)]">
            <SceneTitleSection
                name="Tracing"
                description="Monitor and analyze distributed traces to understand service performance and debug issues."
                resourceType={{
                    type: 'tracing',
                }}
                actions={
                    <>
                        <LemonButton size="small" type="secondary" icon={<IconFeedback />} onClick={onFeedbackClick}>
                            Feedback
                        </LemonButton>
                        <LemonButton
                            to={TRACING_DOCS_URL}
                            onClick={onDocsLinkClick}
                            type="secondary"
                            size="small"
                            targetBlank
                        >
                            Documentation
                        </LemonButton>
                    </>
                }
            />
            <LemonBanner
                type="warning"
                dismissKey="tracing-beta-notice"
                action={{
                    icon: <IconFeedback />,
                    children: 'Share feedback',
                    onClick: onFeedbackClick,
                }}
            >
                Tracing is now in beta. Please share feedback on how to improve the product.
            </LemonBanner>
            <TracingSetupPrompt>
                <TracingFilterBar />
                <SceneDivider />
                <TracingSparkline
                    sparklineData={sparklineData}
                    sparklineLoading={sparklineLoading || (isDurationMode && durationHistogramLoading)}
                    onDateRangeChange={setDateRange}
                    displayTimezone="UTC"
                    compare={compareConfig}
                    visibleRowDateRange={visibleRowDateRange}
                    durationHistogram={isDurationMode ? durationHistogramData : null}
                    visibleRowDurationRange={visibleRowDurationRange}
                />
                <div className="flex flex-row gap-2 flex-1 min-h-0">
                    {facetRailEnabled && !facetRailCollapsed && <FacetRail />}
                    <div className="flex flex-col gap-2 flex-1 min-w-0 min-h-0">
                        <TracingDisplayBar />
                        {operationsViewEnabled && activeTracingTab === 'operations' ? (
                            <OperationsTable
                                rows={aggregation.current}
                                loading={aggregationLoading}
                                windowMs={operationsWindowMs}
                                onRowClick={(row) =>
                                    router.actions.push(urls.tracingOperation(row.service_name, row.name))
                                }
                            />
                        ) : compareMode ? (
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
            </TracingSetupPrompt>
            <TraceDrawer
                isOpen={isTraceOpen}
                traceId={selectedTraceId}
                ts={selectedTraceTs}
                spans={openTraceSpans}
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
        </SceneContent>
    )
}
