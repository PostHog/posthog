import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import {
    TRACING_AGENT_HEADLINES,
    apmSpansQueryToViewerFilters,
    apmTraceGetToTraceId,
    buildTracingAgentContext,
} from './tracingAgentContext'
import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingViewerLogic } from './tracingViewerLogic'

/**
 * Scene-level PostHog AI integration for the tracing viewer. Attaches the exploring-apm-traces
 * skill, the tracing MCP tool catalog, and the live viewer state as agent context, mirrors a
 * query-apm-spans call back onto the open viewer, and opens the trace an apm-trace-get call
 * fetched in the drawer. Resolves the viewer instance from the enclosing BindLogic. Renders nothing.
 */
export function TracingAgentIntegration(): null {
    const { filters } = useValues(tracingFiltersLogic)
    const { setFilters } = useActions(tracingFiltersLogic)
    const { selectedTraceId, selectedSpanId } = useValues(tracingViewerLogic)
    const { openTrace } = useActions(tracingViewerLogic)

    // Debounced so per-keystroke filter edits don't re-serialize the viewer state on every change.
    const debouncedFilters = useDebouncedValue(filters, 500)
    const contextItems = useMemo(
        () =>
            buildTracingAgentContext(
                debouncedFilters,
                selectedTraceId ? { traceId: selectedTraceId, spanId: selectedSpanId } : null
            ),
        [debouncedFilters, selectedTraceId, selectedSpanId]
    )

    useSceneAgentPanel({
        sceneKey: 'tracing',
        contextItems,
        headlines: TRACING_AGENT_HEADLINES,
    })

    useMcpToolApplyBack({
        tools: ['query-apm-spans'],
        targetKey: `tracing-viewer:${TRACING_SCENE_VIEWER_ID}`,
        onApply: (_event, { innerInput }) => {
            if (!innerInput) {
                return
            }
            setFilters(apmSpansQueryToViewerFilters(innerInput))
        },
    })

    useMcpToolApplyBack({
        tools: ['apm-trace-get'],
        targetKey: `tracing-viewer-trace:${TRACING_SCENE_VIEWER_ID}`,
        onApply: (_event, { innerInput }) => {
            const traceId = innerInput ? apmTraceGetToTraceId(innerInput) : null
            if (traceId) {
                openTrace(traceId)
            }
        },
    })

    return null
}
