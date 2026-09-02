import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { buildLogsAgentContext, LOGS_AGENT_HEADLINES, logsQueryToViewerFilters } from './logsAgentContext'
import { LOGS_SCENE_VIEWER_ID, logsSceneLogic } from './logsSceneLogic'

/**
 * Scene-level PostHog AI integration for the logs viewer. Attaches the investigating-logs skill, the
 * logs MCP tool catalog, and the live viewer filter state as agent context, and mirrors a query-logs
 * tool call back onto the open viewer so the user sees the agent's query both in chat and on screen.
 * Renders nothing.
 */
export function LogsAgentIntegration({ activeTabIsViewer }: { activeTabIsViewer: boolean }): null {
    const { filters } = useValues(logsSceneLogic)
    const { setFilters } = useActions(logsSceneLogic)

    // Debounced so per-keystroke search edits don't re-serialize the filter state on every change.
    const debouncedFilters = useDebouncedValue(filters, 500)

    const contextItems = useMemo(() => buildLogsAgentContext(debouncedFilters), [debouncedFilters])

    useSceneAgentPanel({
        sceneKey: 'logs',
        contextItems,
        headlines: LOGS_AGENT_HEADLINES,
    })

    useMcpToolApplyBack({
        tools: ['query-logs'],
        targetKey: `logs-viewer:${LOGS_SCENE_VIEWER_ID}`,
        // Only mirror onto the viewer while the user is looking at it, so a query the agent runs while
        // the user is on the SQL or alerts tab does not silently rewrite the hidden viewer's filters.
        active: activeTabIsViewer,
        onApply: (_event, { innerInput }) => {
            if (!innerInput) {
                return
            }
            setFilters(logsQueryToViewerFilters(innerInput))
        },
    })

    return null
}
