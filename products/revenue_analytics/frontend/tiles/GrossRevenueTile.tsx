import { IconInfo } from '@posthog/icons'
import { LemonSegmentedButton, LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, RevenueAnalyticsInsightsQueryGroupBy } from '~/queries/schema/schema-general'
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
    const { queries, grossRevenueGroupBy } = useValues(revenueAnalyticsLogic)
    const { setGrossRevenueGroupBy } = useActions(revenueAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    const OPTIONS: LemonSegmentedButtonOption<RevenueAnalyticsInsightsQueryGroupBy>[] = [
        { label: 'All', value: 'all' },
        {
            label: 'Product',
            value: 'product',
            disabledReason: featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_PRODUCT_GROUPING] ? undefined : 'Coming soon',
        },
        {
            label: 'Cohort',
            value: 'cohort',
            disabledReason: featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_COHORT_GROUPING] ? undefined : 'Coming soon',
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between">
                <h3 className="text-lg font-semibold">
                    Gross Revenue&nbsp;
                    <Tooltip title="Gross revenue is the total amount of revenue generated from all sources, including all products and services.">
                        <IconInfo />
                    </Tooltip>
                </h3>
                <span className="flex items-center gap-1 text-muted-alt">
                    Group by&nbsp;
                    <LemonSegmentedButton<RevenueAnalyticsInsightsQueryGroupBy>
                        options={OPTIONS}
                        value={grossRevenueGroupBy}
                        onChange={setGrossRevenueGroupBy}
                    />
                </span>
            </div>

            <Query query={query} readOnly context={context} />
        </div>
    )
}
