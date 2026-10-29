import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { SavedInsightsTable } from 'scenes/saved-insights/SavedInsightsTable'

import { InsightModel } from '~/types'

import { insightDashboardModalLogic } from './insightDashboardModalLogic'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardUpdatesInProgress, isInsightInDashboard } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)

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

    return (
        <SavedInsightsTable
            isSelected={(insight) => isInsightInDashboard(insight, dashboard?.tiles)}
            onToggle={handleToggle}
            isToggling={(insight) => !!dashboardUpdatesInProgress[insight.id]}
        />
    )
}
