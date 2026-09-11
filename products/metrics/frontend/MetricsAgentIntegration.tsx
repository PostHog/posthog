import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { METRICS_AGENT_HEADLINES, buildMetricsAgentContext, metricsQueryToViewerState } from './metricsAgentContext'
import { MetricsSceneActiveTab, metricsSceneLogic } from './metricsSceneLogic'

// The two tabs that show the chart the agent's query lands on. On the SQL and fundamentals tabs the
// user has their own work open, so a query-metrics call leaves it alone instead of pulling the tab.
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

    // Debounced so per-keystroke metric name and formula edits don't re-serialize the query on
    // every change.
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
            // The overview tab has no chart of its own, so the series the agent queried would land
            // out of sight without this.
            setActiveTab('viewer')
        },
    })

    return null
}
