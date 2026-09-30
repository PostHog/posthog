import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightsTable } from './InsightsTable'

/**
 * InsightsTable for use in a dashboard.
 */
export function DashboardInsightsTable(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    return (
        <InsightsTable
            filterKey={`dashboard_${insightProps.dashboardItemId}`}
            embedded
            canCheckUncheckSeries={false}
            editMode={false}
        />
    )
}
