import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DashboardPlacement } from '~/types'

import { EVALUATION_METRICS_COLLECTION_ID } from './evaluations/components/EvaluationMetrics'
import { evaluationMetricsLogic } from './evaluations/evaluationMetricsLogic'
import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID, llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsDashboardLogic } from './tabs/llmAnalyticsDashboardLogic'

export function LLMAnalyticsReloadAction(): JSX.Element {
    const { activeTab } = useValues(llmAnalyticsSharedLogic)
    const { selectedDashboardId } = useValues(llmAnalyticsDashboardLogic)

    const shouldUseDashboardLogic = selectedDashboardId && activeTab === 'dashboard'
    const dashboardLogicInstance = dashboardLogic({
        id: selectedDashboardId || 0,
        placement: DashboardPlacement.Builtin,
    })
    const {
        itemsLoading: dashboardLoading,
        effectiveLastRefresh,
        refreshMetrics,
        dashboardLoadData,
    } = useValues(dashboardLogicInstance)
    const { triggerDashboardRefresh } = useActions(dashboardLogicInstance)

    const { reloadAll } = useActions(dataNodeCollectionLogic({ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID }))
    const { reloadAll: reloadEvaluationMetrics } = useActions(
        dataNodeCollectionLogic({ key: EVALUATION_METRICS_COLLECTION_ID })
    )
    const { refreshMetrics: refreshEvaluationMetrics } = useActions(evaluationMetricsLogic)
    const { loadEvaluations } = useActions(llmEvaluationsLogic)

    const isLoading = shouldUseDashboardLogic ? dashboardLoading : false
    const lastRefresh = shouldUseDashboardLogic ? effectiveLastRefresh : null

    const handleRefresh = (): void => {
        if (activeTab === 'dashboard') {
            triggerDashboardRefresh()
        } else if (activeTab === 'evaluations') {
            // Refresh evaluations list and metrics
            loadEvaluations()
            refreshEvaluationMetrics()
            reloadEvaluationMetrics()
        } else {
            reloadAll()
        }
    }

    return (
        <LemonButton
            onClick={handleRefresh}
            type="secondary"
            icon={isLoading ? <Spinner textColored /> : <IconRefresh />}
            size="small"
            disabledReason={isLoading ? 'Loading...' : undefined}
        >
            <span className="dashboard-items-action-refresh-text">
                {isLoading ? (
                    <>
                        {shouldUseDashboardLogic && refreshMetrics?.total ? (
                            <>
                                {dashboardLoadData?.action === 'initial_load' ? 'Loaded' : 'Refreshed'}{' '}
                                {refreshMetrics.completed} out of {refreshMetrics.total}
                            </>
                        ) : (
                            <>
                                {shouldUseDashboardLogic && dashboardLoadData?.action === 'initial_load'
                                    ? 'Loading'
                                    : 'Refreshing'}
                                ...
                            </>
                        )}
                    </>
                ) : lastRefresh && dayjs().diff(dayjs(lastRefresh), 'hour') < 24 ? (
                    <div className="flex items-center gap-1">
                        <span>Last refreshed</span>
                        <TZLabel time={lastRefresh} />
                    </div>
                ) : (
                    'Refresh'
                )}
            </span>
        </LemonButton>
    )
}
