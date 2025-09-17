import { useValues } from 'kea'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import {
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    RevenueAnalyticsQuery,
    buildDashboardItemId,
    revenueAnalyticsLogic,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.GROSS_REVENUE
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

const EMPTY_STATE_HEADING = 'No gross revenue data available'
const EMPTY_STATE_DETAIL =
    'Please try adjusting your query or filters. Also, make sure your revenue events are properly configured in the settings.'

export const GrossRevenueTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(
        () => ({
            insightProps: { ...INSIGHT_PROPS, query },
            emptyStateHeading: EMPTY_STATE_HEADING,
            emptyStateDetail: EMPTY_STATE_DETAIL,
        }),
        [query]
    )

    return <Query attachTo={revenueAnalyticsLogic} query={query} readOnly context={context} />
}
