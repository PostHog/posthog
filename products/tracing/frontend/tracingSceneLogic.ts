import { actions, connect, kea, path, reducers, selectors } from 'kea'

import type { Span, TraceSummary } from './data/mockTraceData'
import { tracingFilterLogic } from './tracingFilterLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'

export type TracingTab = 'traces' | 'service-map'

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),

    connect({ values: [tracingFilterLogic, ['traces']] }),

    actions({
        setActiveTab: (tab: TracingTab) => ({ tab }),
        setSelectedTraceId: (traceId: string | null) => ({ traceId }),
        setSelectedSpanId: (spanId: string | null) => ({ spanId }),
        setHoveredServiceNodeId: (nodeId: string | null) => ({ nodeId }),
    }),

    reducers({
        activeTab: [
            'traces' as TracingTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedTraceId: [
            null as string | null,
            {
                setSelectedTraceId: (_, { traceId }) => traceId,
                setActiveTab: () => null,
            },
        ],
        selectedSpanId: [
            null as string | null,
            {
                setSelectedSpanId: (_, { spanId }) => spanId,
                setSelectedTraceId: () => null,
                setActiveTab: () => null,
            },
        ],
        hoveredServiceNodeId: [
            null as string | null,
            {
                setHoveredServiceNodeId: (_, { nodeId }) => nodeId,
            },
        ],
    }),

    selectors({
        selectedTrace: [
            (s) => [s.selectedTraceId, s.traces],
            (selectedTraceId: string | null, traces: TraceSummary[]): TraceSummary | null =>
                selectedTraceId ? (traces.find((t) => t.trace_id === selectedTraceId) ?? null) : null,
        ],
        selectedSpan: [
            (s) => [s.selectedSpanId, s.selectedTrace],
            (selectedSpanId: string | null, selectedTrace: TraceSummary | null): Span | null =>
                selectedSpanId ? (selectedTrace?.spans.find((s) => s.span_id === selectedSpanId) ?? null) : null,
        ],
    }),
])
