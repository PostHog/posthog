import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { IconFeedback } from 'lib/lemon-ui/icons'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { TracingSetupPrompt } from './components/SetupPrompt/SetupPrompt'
import { VirtualizedSpanList } from './components/VirtualizedSpanList/VirtualizedSpanList'
import { TraceCompareFlame } from './TraceCompareFlame'
import { TraceCompareTable } from './TraceCompareTable'
import { TraceFlameChart } from './TraceFlameChart'
import { tracingDataLogic } from './tracingDataLogic'
import { TracingFilterBar } from './TracingFilterBar'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingSceneLogic, TracingSceneLogicProps } from './tracingSceneLogic'
import { TracingSparkline } from './TracingSparkline'
import { TracingTabIdProvider, useTracingTabId } from './TracingTabContext'
import type { Span } from './types'

const TRACING_FEEDBACK_SURVEY_ID = '019e6a26-4943-0000-24a0-dc46310f6b7c'
const TRACING_DOCS_URL = 'https://posthog.com/docs/tracing'

export const scene: SceneExport<TracingSceneLogicProps> = {
    component: TracingScene,
    logic: tracingSceneLogic,
    productKey: ProductKey.TRACING,
}

export default function TracingScene(props: TracingSceneLogicProps = {}): JSX.Element {
    const sceneLogic = tracingSceneLogic(props)
    // Keep filters + data logic alive across tab switches by attaching them to the scene
    // root. The root itself is kept mounted by `tabAwareScene()` even when the tab is inactive.
    useAttachedLogic(tracingFiltersLogic({ tabId: props.tabId }), sceneLogic)
    useAttachedLogic(tracingDataLogic({ tabId: props.tabId }), sceneLogic)

    return (
        <TracingTabIdProvider value={props.tabId}>
            <TracingSceneContents />
        </TracingTabIdProvider>
    )
}

function TracingSceneContents(): JSX.Element {
    const tabId = useTracingTabId()
    const {
        rootSpans,
        spansLoading,
        isTraceModalOpen,
        selectedTraceId,
        linkedSpanId,
        sparklineData,
        sparklineLoading,
        totalSpansMatchingFilters,
        modalSpans,
        isLoadingFullTrace,
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
        expandedSpanIds,
    } = useValues(tracingSceneLogic({ tabId }))
    const {
        openTraceModal,
        closeTraceModal,
        setDateRange,
        setOverlayWindows,
        openCompareFlame,
        closeCompareFlame,
        fetchNextPage,
        setVisibleRowRange,
        toggleExpandSpan,
    } = useActions(tracingSceneLogic({ tabId }))
    const { addProductIntent } = useActions(teamLogic)
    const compareMode = filters.compareMode

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
                dismissKey="tracing-alpha-notice"
                action={{
                    icon: <IconFeedback />,
                    children: 'Share feedback',
                    onClick: onFeedbackClick,
                }}
            >
                Tracing is in alpha. Expect bugs, missing features, and breaking changes.
            </LemonBanner>
            <TracingSetupPrompt>
                <TracingSparkline
                    sparklineData={sparklineData}
                    sparklineLoading={sparklineLoading}
                    onDateRangeChange={setDateRange}
                    displayTimezone="UTC"
                    compare={compareConfig}
                    visibleRowDateRange={visibleRowDateRange}
                />
                <SceneDivider />
                <TracingFilterBar />
                {!sparklineLoading && totalSpansMatchingFilters > 0 && (
                    <div className="text-xs text-muted px-1">
                        {totalSpansMatchingFilters.toLocaleString()} spans matching filters
                    </div>
                )}
                {compareMode ? (
                    <div className="flex flex-col flex-1 min-h-0 overflow-auto">
                        <TraceCompareTable
                            current={aggregation.current}
                            previous={aggregation.previous}
                            loading={aggregationLoading}
                            onRowClick={(row) => openCompareFlame(row.name, row.service_name)}
                        />
                    </div>
                ) : (
                    <VirtualizedSpanList
                        dataSource={rootSpans}
                        loading={spansLoading}
                        hasMoreToLoad={hasMoreToLoad}
                        onLoadMore={fetchNextPage}
                        onVisibleRowRangeChange={setVisibleRowRange}
                        expandedSpanIds={expandedSpanIds}
                        onToggleExpand={toggleExpandSpan}
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
                            openTraceModal(span.trace_id)
                        }}
                    />
                )}
            </TracingSetupPrompt>
            <LemonModal
                title={`Trace ${selectedTraceId}`}
                isOpen={isTraceModalOpen}
                onClose={closeTraceModal}
                width="90vw"
            >
                <div className="relative min-h-32">
                    {isLoadingFullTrace && <SpinnerOverlay />}
                    <TraceFlameChart spans={modalSpans} highlightSpanId={linkedSpanId} />
                </div>
            </LemonModal>
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
