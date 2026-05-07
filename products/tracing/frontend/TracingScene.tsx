import { useActions, useValues } from 'kea'

import { LemonModal, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { formatDuration, TraceFlameChart } from './TraceFlameChart'
import { TracingChartPanel } from './TracingChartPanel'
import { TracingFilterBar } from './TracingFilterBar'
import { tracingSceneLogic } from './tracingSceneLogic'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from './types'
import type { Span } from './types'

export const scene: SceneExport = {
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

export default function TracingScene(): JSX.Element {
    const {
        rootSpans,
        spansLoading,
        isTraceModalOpen,
        selectedTraceId,
        sparklineLoading,
        totalSpansMatchingFilters,
        modalSpans,
        isLoadingFullTrace,
        bubbleUpRows,
        bubbleUpRowsLoading,
    } = useValues(tracingSceneLogic)
    const { openTraceModal, closeTraceModal, clearBubbleUp } = useActions(tracingSceneLogic)

    const bubbleUpModalOpen = bubbleUpRows != null || bubbleUpRowsLoading
    const showFilteredSpanCount = !sparklineLoading && totalSpansMatchingFilters > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Tracing"
                description="Monitor and analyze distributed traces to understand service performance and debug issues."
                resourceType={{
                    type: 'tracing',
                }}
            />
            <TracingChartPanel displayTimezone="UTC" />
            <SceneDivider />
            <TracingFilterBar />
            {showFilteredSpanCount ? (
                <div className="text-xs text-muted px-1">
                    {totalSpansMatchingFilters.toLocaleString()} spans matching filters
                </div>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={rootSpans}
                loading={spansLoading}
                rowKey="uuid"
                emptyState="No spans found"
                onRow={(span) => ({
                    onClick: () => {
                        ;(document.activeElement as HTMLElement | null)?.blur?.()
                        openTraceModal(span.trace_id)
                    },
                    className: 'cursor-pointer',
                })}
            />
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
                title="BubbleUp"
                description="Attributes enriched in your selection versus the baseline."
                isOpen={bubbleUpModalOpen}
                onClose={() => clearBubbleUp()}
                width="800px"
            >
                {bubbleUpRowsLoading ? (
                    <SpinnerOverlay />
                ) : (
                    <LemonTable
                        loading={false}
                        dataSource={bubbleUpRows ?? []}
                        columns={[
                            { title: 'Key', dataIndex: 'attribute_key' },
                            { title: 'Value', dataIndex: 'attribute_value' },
                            { title: 'Type', dataIndex: 'attribute_type' },
                            { title: 'Lift', dataIndex: 'lift' },
                            { title: 'In selection', dataIndex: 'inset_count' },
                            { title: 'Baseline', dataIndex: 'baseline_count' },
                        ]}
                        rowKey={(row) => `${row.attribute_key}:${row.attribute_value}:${row.attribute_type}`}
                    />
                )}
            </LemonModal>
        </SceneContent>
    )
}
