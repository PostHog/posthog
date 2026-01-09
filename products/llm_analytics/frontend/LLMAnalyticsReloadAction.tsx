import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'
import { DashboardPlacement } from '~/types'

import { EVALUATION_METRICS_COLLECTION_ID } from './evaluations/components/EvaluationMetrics'
import { evaluationMetricsLogic } from './evaluations/evaluationMetricsLogic'
import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID, llmAnalyticsLogic } from './llmAnalyticsLogic'

export function LLMAnalyticsReloadAction(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        activeTab,
        selectedDashboardId,
        isRefreshing: oldTilesRefreshing,
        tabsLastRefresh,
    } = useValues(llmAnalyticsLogic)
    const { refreshAllDashboardItems } = useActions(llmAnalyticsLogic)

    const useCustomizableDashboard =
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

    const shouldUseDashboardLogic = selectedDashboardId && useCustomizableDashboard && activeTab === 'dashboard'
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

    const dataNodeCollection = dataNodeCollectionLogic({ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID })
    const { reloadAll } = useActions(dataNodeCollection)
    const { areAnyLoading } = useValues(dataNodeCollection)
    const { reloadAll: reloadEvaluationMetrics } = useActions(
        dataNodeCollectionLogic({ key: EVALUATION_METRICS_COLLECTION_ID })
    )
    const { refreshMetrics: refreshEvaluationMetrics } = useActions(evaluationMetricsLogic)
    const { loadEvaluations } = useActions(llmEvaluationsLogic)

    const isLoading = shouldUseDashboardLogic
        ? dashboardLoading
        : activeTab === 'dashboard'
          ? oldTilesRefreshing
          : areAnyLoading
    const lastRefresh = shouldUseDashboardLogic ? effectiveLastRefresh : tabsLastRefresh

    const handleRefresh = (): void => {
        if (activeTab === 'dashboard') {
            if (shouldUseDashboardLogic) {
                // New customizable dashboard
                triggerDashboardRefresh()
            } else {
                // Old hardcoded tiles
                refreshAllDashboardItems()
            }
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

/**
 * Custom reload button for LLM Analytics DataTables.
 * Uses dataNodeLogic for reload functionality (like the default Reload component)
 * but displays "Last refreshed [time]" from llmAnalyticsLogic.
 */
export function LLMAnalyticsDataTableReload(): JSX.Element {
    const { responseLoading, query } = useValues(dataNodeLogic)
    const { loadData, cancelQuery } = useActions(dataNodeLogic)
    const { tabsLastRefresh } = useValues(llmAnalyticsLogic)

    return (
        <LemonButton
            type="secondary"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
                }
            }}
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
            size="small"
        >
            {responseLoading ? (
                'Cancel'
            ) : tabsLastRefresh && dayjs().diff(dayjs(tabsLastRefresh), 'hour') < 24 ? (
                <div className="flex items-center gap-1">
                    <span>Last refreshed</span>
                    <TZLabel time={tabsLastRefresh} />
                </div>
            ) : (
                'Reload'
            )}
        </LemonButton>
    )
}
