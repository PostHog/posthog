import { useActions, useValues } from 'kea'

import { LemonModal, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TraceCompareFlame } from './TraceCompareFlame'
import { TraceCompareTable } from './TraceCompareTable'
import { formatDuration, TraceFlameChart } from './TraceFlameChart'
import { tracingDataLogic } from './tracingDataLogic'
import { TracingFilterBar } from './TracingFilterBar'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingSceneLogic, TracingSceneLogicProps } from './tracingSceneLogic'
import { TracingSparkline } from './TracingSparkline'
import { TracingTabIdProvider, useTracingTabId } from './TracingTabContext'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from './types'
import type { Span } from './types'

export const scene: SceneExport<TracingSceneLogicProps> = {
    component: TracingScene,
    logic: tracingSceneLogic,
    productKey: ProductKey.TRACING,
}

function isRootSpan(span: Span): boolean {
    return !span.parent_span_id
}

const columns: LemonTableColumns<Span> = [
    {
        title: 'Timestamp',
        dataIndex: 'timestamp',
        render: (_, span) => new Date(span.timestamp).toLocaleString(),
    },
    {
        title: 'Name',
        dataIndex: 'name',
        render: (_, span) => (
            <span className="flex items-center gap-2">
                {span.name}
                {isRootSpan(span) && (
                    <LemonTag type="highlight" size="small">
                        trace
                    </LemonTag>
                )}
            </span>
        ),
    },
    {
        title: 'Service',
        dataIndex: 'service_name',
        render: (_, span) => <LemonTag>{span.service_name}</LemonTag>,
    },
    {
        title: 'Kind',
        dataIndex: 'kind',
        render: (_, span) => SPAN_KIND_LABELS[span.kind] ?? span.kind,
    },
    {
        title: 'Duration',
        dataIndex: 'duration_nano',
        render: (_, span) => formatDuration(span.duration_nano),
    },
    {
        title: 'Status',
        dataIndex: 'status_code',
        render: (_, span) => {
            const status = STATUS_CODE_LABELS[span.status_code] ?? {
                label: String(span.status_code),
                type: 'default' as const,
            }
            return <LemonTag type={status.type}>{status.label}</LemonTag>
        },
    },
    {
        title: 'Trace ID',
        dataIndex: 'trace_id',
        render: (_, span) => <span className="font-mono text-xs">{span.trace_id.substring(0, 16)}...</span>,
    },
]

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
    } = useValues(tracingSceneLogic({ tabId }))
    const { openTraceModal, closeTraceModal, setDateRange, setOverlayWindows, openCompareFlame, closeCompareFlame } =
        useActions(tracingSceneLogic({ tabId }))
    const compareMode = filters.compareMode

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
        <SceneContent>
            <SceneTitleSection
                name="Tracing"
                description="Monitor and analyze distributed traces to understand service performance and debug issues."
                resourceType={{
                    type: 'tracing',
                }}
            />
            <TracingSparkline
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={setDateRange}
                displayTimezone="UTC"
                compare={compareConfig}
            />
            <SceneDivider />
            <TracingFilterBar />
            {!sparklineLoading && totalSpansMatchingFilters > 0 && (
                <div className="text-xs text-muted px-1">
                    {totalSpansMatchingFilters.toLocaleString()} spans matching filters
                </div>
            )}
            {compareMode ? (
                <TraceCompareTable
                    current={aggregation.current}
                    previous={aggregation.previous}
                    loading={aggregationLoading}
                    onRowClick={(row) => openCompareFlame(row.name, row.service_name)}
                />
            ) : (
                <LemonTable
                    columns={columns}
                    dataSource={rootSpans}
                    loading={spansLoading}
                    rowKey="uuid"
                    emptyState="No spans found"
                    onRow={(span) => ({
                        onClick: () => {
                            // Clicking a row leaves the scrollable <main tabIndex="0"> as the active
                            // element; react-modal then scrolls it back into view when restoring focus
                            // on close. Blur so the restore target is <body>, which doesn't scroll.
                            ;(document.activeElement as HTMLElement | null)?.blur?.()
                            openTraceModal(span.trace_id)
                        },
                        className: 'cursor-pointer',
                    })}
                />
            )}
            <LemonModal
                title={`Trace ${selectedTraceId}`}
                isOpen={isTraceModalOpen}
                onClose={closeTraceModal}
                width="90vw"
            >
                <div className="relative min-h-32">
                    {isLoadingFullTrace && <SpinnerOverlay />}
                    <TraceFlameChart spans={modalSpans} />
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
