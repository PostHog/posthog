import { useValues } from 'kea'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import {
    buildDashboardItemId,
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    revenueAnalyticsLogic,
    RevenueAnalyticsQuery,
} from '../revenueAnalyticsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const QUERY_ID = RevenueAnalyticsQuery.REVENUE
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const RevenueTile = (): JSX.Element | null => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    if (!featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_MRR]) {
        return null
    }

    return <Query query={query} readOnly context={context} />
}
