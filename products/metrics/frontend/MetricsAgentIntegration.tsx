import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { METRICS_AGENT_HEADLINES, buildMetricsAgentContext, metricsQueryToViewerState } from './metricsAgentContext'
import { MetricsSceneActiveTab, metricsSceneLogic } from './metricsSceneLogic'

// The tabs holding the chart. Elsewhere the user has their own work open, so leave it alone.
const APPLY_BACK_TABS: MetricsSceneActiveTab[] = ['overview', 'viewer']

/**
 * Scene-level PostHog AI integration for the metrics scene. Attaches the
 * investigating-metric-anomalies skill, the metrics MCP tool catalog, and the live viewer query as
 * agent context, and mirrors a query-metrics tool call back onto the viewer so the user sees the
 * agent's series both in chat and on screen. Renders nothing.
 */
export function MetricsAgentIntegration(): null {
    const { viewerClauses, formula, dateFrom, dateTo, activeTab } = useValues(metricsSceneLogic)
    const { setClauses, setDateFrom, setDateTo, setActiveTab } = useActions(metricsSceneLogic)

    // Debounced so a keystroke in the metric name or formula doesn't re-serialize the whole query.
    const debouncedClauses = useDebouncedValue(viewerClauses, 500)
    const debouncedFormula = useDebouncedValue(formula, 500)

    const contextItems = useMemo(
        () =>
            buildMetricsAgentContext({
                clauses: debouncedClauses,
                formula: debouncedFormula,
                dateFrom,
                dateTo,
                activeTab,
            }),
        [debouncedClauses, debouncedFormula, dateFrom, dateTo, activeTab]
    )

    useSceneAgentPanel({
        sceneKey: 'metrics',
        contextItems,
        headlines: METRICS_AGENT_HEADLINES,
    })

    useMcpToolApplyBack({
        tools: ['query-metrics'],
        targetKey: 'metrics-viewer',
        active: APPLY_BACK_TABS.includes(activeTab),
        onApply: (_event, { innerInput }) => {
            if (!innerInput) {
                return
            }
            const next = metricsQueryToViewerState(innerInput)
            if (!next) {
                return
            }
            setClauses(next.clauses, next.formula)
            setDateFrom(next.dateFrom)
            setDateTo(next.dateTo)
            // Overview has no chart of its own, so the queried series would land out of sight.
            setActiveTab('viewer')
        },
    })

    return null
}
