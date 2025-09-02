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

const QUERY_ID = RevenueAnalyticsQuery.MRR
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const MRRTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    return <Query query={query} readOnly context={context} />
}
