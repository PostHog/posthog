import { useValues } from 'kea'
import { useMemo } from 'react'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import {
    buildDashboardItemId,
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    revenueAnalyticsLogic,
    RevenueAnalyticsQuery,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.REVENUE_CHURN
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const RevenueChurnTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    return <div className="flex flex-col gap-1">TODO: {JSON.stringify({ query, context })}</div>
}
