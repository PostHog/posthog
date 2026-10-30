import { useActions, useMountedLogic, useValues } from 'kea'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'

import type { InsightLogicProps } from '~/types'

import {
    getToolOutputRecord,
    runnerPanelLogic,
    useAttachedContext,
    useMcpToolApplyBack,
} from 'products/posthog_ai/frontend/api/logics'

import { explainChartLogic } from './explainChartLogic'

export function ExplainChartAgentBridge({ insightProps }: { insightProps: InsightLogicProps }): null {
    useMountedLogic(explainChartLogic(insightProps))
    useMountedLogic(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }))
    const { explainAvailable, followUpContext } = useValues(explainChartLogic(insightProps))
    const { explainChartToolCompleted } = useActions(explainChartLogic(insightProps))

    useMcpToolApplyBack({
        tools: ['explain-chart'],
        targetKey: `explain-chart-${keyForInsightLogicProps('new')(insightProps)}`,
        active: explainAvailable,
        onApply: (event, { innerInput }) =>
            explainChartToolCompleted(
                innerInput,
                getToolOutputRecord({ rawOutput: event.invocation.output, status: event.invocation.status })
            ),
    })
    useAttachedContext(followUpContext ? [followUpContext] : null)

    return null
}
