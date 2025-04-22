import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
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

const QUERY_ID = RevenueAnalyticsQuery.GROSS_REVENUE
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const GrossRevenueTile = (): JSX.Element => {
    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    return (
        <div className="flex flex-col gap-1">
            <h3 className="text-lg font-semibold">
                Gross Revenue&nbsp;
                <Tooltip title="Gross revenue is the total amount of revenue generated from all sources, including all products and services.">
                    <IconInfo />
                </Tooltip>
            </h3>

            <Query query={query} readOnly context={context} />
        </div>
    )
}
