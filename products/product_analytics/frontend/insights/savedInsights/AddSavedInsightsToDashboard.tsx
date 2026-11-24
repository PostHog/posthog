import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { QuillSavedInsightsTable } from 'scenes/saved-insights/QuillSavedInsightsTable'
import { SavedInsightsTable } from 'scenes/saved-insights/SavedInsightsTable'

import { InsightModel } from '~/types'

import { insightDashboardModalLogic } from './insightDashboardModalLogic'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardUpdatesInProgress, isInsightInDashboard } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        if (dashboard?.tiles) {
            syncOptimisticStateWithDashboard(dashboard.tiles)
        }
    }, [dashboard?.tiles, syncOptimisticStateWithDashboard])

    const handleToggle = (insight: InsightModel): void => {
        if (!dashboard?.id) {
            return
        }
        toggleInsightOnDashboard(insight, dashboard.id, isInsightInDashboard(insight, dashboard.tiles))
    }

    const Table = todayRailNav ? QuillSavedInsightsTable : SavedInsightsTable

    return (
        <Table
            isSelected={(insight) => isInsightInDashboard(insight, dashboard?.tiles)}
            onToggle={handleToggle}
            isToggling={(insight) => !!dashboardUpdatesInProgress[insight.id]}
        />
    )
}
