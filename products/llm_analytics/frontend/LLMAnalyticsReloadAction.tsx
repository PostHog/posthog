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
import { DashboardPlacement } from '~/types'

import { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID, llmAnalyticsLogic } from './llmAnalyticsLogic'

export function LLMAnalyticsReloadAction(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, selectedDashboardId, isRefreshing: oldTilesRefreshing } = useValues(llmAnalyticsLogic)
    const { refreshAllDashboardItems } = useActions(llmAnalyticsLogic)

    const useCustomizableDashboard = featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD]

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

    const { reloadAll } = useActions(dataNodeCollectionLogic({ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID }))

    const isLoading = shouldUseDashboardLogic ? dashboardLoading : oldTilesRefreshing
    const lastRefresh = shouldUseDashboardLogic ? effectiveLastRefresh : null

    const handleRefresh = (): void => {
        if (activeTab === 'dashboard') {
            if (shouldUseDashboardLogic) {
                // New customizable dashboard
                triggerDashboardRefresh()
            } else {
                // Old hardcoded tiles
                refreshAllDashboardItems()
            }
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
