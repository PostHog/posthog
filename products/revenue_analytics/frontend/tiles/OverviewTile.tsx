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

const QUERY_ID = RevenueAnalyticsQuery.OVERVIEW
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const OverviewTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    return <Query attachTo={revenueAnalyticsLogic} query={query} readOnly context={context} />
}
