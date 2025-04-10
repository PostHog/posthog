import { useValues } from 'kea'

import {
    buildDashboardItemId,
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    revenueAnalyticsLogic,
    RevenueAnalyticsQuery,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.OVERVIEW
const QUERY_CONTEXT = {
    insightProps: {
        dashboardItemId: buildDashboardItemId(QUERY_ID),
        loadPriority: QUERY_ID,
        dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    },
}

export const OverviewTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    return (
        <div className="flex flex-col gap-1">
            TODO: {JSON.stringify({ query, context: QUERY_CONTEXT })}
            {/* <h3 className="text-lg font-semibold">Overview</h3>
        <p className="text-sm text-gray-500">
            Overview of your revenue data.
        </p>

        <Query query={query} readOnly context={context} /> */}
        </div>
    )
}
