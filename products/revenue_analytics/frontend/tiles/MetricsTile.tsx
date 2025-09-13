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
import { revenueAnalyticsSettingsLogic } from '../settings/revenueAnalyticsSettingsLogic'

const QUERY_ID = RevenueAnalyticsQuery.METRICS
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

const EMPTY_STATE_HEADING = 'No data available'
const EMPTY_STATE_DETAIL_NO_EVENTS = 'Please try adjusting your query or filters.'
const EMPTY_STATE_DETAIL_WITH_EVENTS = (
    <span>
        Please try adjusting your query or filters. If you're using revenue events then make sure you've configured what
        the <code>subscription_id</code> property is to properly track subscriptions/customer churn metrics.
    </span>
)
export const MetricsTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const { events } = useValues(revenueAnalyticsSettingsLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(
        () => ({
            insightProps: { ...INSIGHT_PROPS, query },
            emptyStateHeading: EMPTY_STATE_HEADING,
            emptyStateDetail: events.length > 0 ? EMPTY_STATE_DETAIL_WITH_EVENTS : EMPTY_STATE_DETAIL_NO_EVENTS,
        }),
        [query, events.length]
    )

    return <Query attachTo={revenueAnalyticsLogic} query={query} readOnly context={context} />
}
