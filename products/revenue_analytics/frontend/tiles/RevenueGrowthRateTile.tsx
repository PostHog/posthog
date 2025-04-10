import { useValues } from 'kea'

import {
    buildDashboardItemId,
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    revenueAnalyticsLogic,
    RevenueAnalyticsQuery,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.REVENUE_GROWTH_RATE
const QUERY_CONTEXT = {
    insightProps: {
        dashboardItemId: buildDashboardItemId(QUERY_ID),
        loadPriority: QUERY_ID,
        dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    },
}

export const RevenueGrowthRateTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    return (
        <div className="flex flex-col gap-1">
            TODO: {JSON.stringify({ query, context: QUERY_CONTEXT })}
            {/* <h3 className="text-lg font-semibold">Revenue Growth Rate</h3>
        <p className="text-sm text-gray-500">
            Revenue growth rate is the percentage change in revenue from one period to another.
        </p>

        <Query query={query} readOnly context={context} /> */}
        </div>
    )
}
