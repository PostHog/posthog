import { useActions, useValues } from 'kea'

import { LemonModal, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { formatDuration, TraceFlameChart } from './TraceFlameChart'
import { TracingFilterBar } from './TracingFilterBar'
import { tracingSceneLogic } from './tracingSceneLogic'
import { TracingSparkline } from './TracingSparkline'
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
        spans,
        spansLoading,
        isTraceModalOpen,
        selectedTraceId,
        sparklineData,
        sparklineLoading,
        totalSpansMatchingFilters,
    } = useValues(tracingSceneLogic)
    const { openTraceModal, closeTraceModal, setDateRange } = useActions(tracingSceneLogic)

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
            />
            <SceneDivider />
            <TracingFilterBar />
            {!sparklineLoading && totalSpansMatchingFilters > 0 && (
                <div className="text-xs text-muted px-1">
                    {totalSpansMatchingFilters.toLocaleString()} spans matching filters
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={rootSpans}
                loading={spansLoading}
                rowKey="uuid"
                emptyState="No spans found"
                onRow={(span) => ({
                    onClick: () => openTraceModal(span.trace_id),
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
                    <TraceFlameChart spans={spans.filter((s) => s.trace_id === selectedTraceId)} />
                </div>
            </LemonModal>
        </SceneContent>
    )
}
