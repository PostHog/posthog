import { IconGraph, IconInfo, IconLineGraph } from '@posthog/icons'
import { LemonDivider, LemonSegmentedButton, LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, RevenueAnalyticsInsightsQueryGroupBy } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import {
    buildDashboardItemId,
    DisplayMode,
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
    const { queries, grossRevenueGroupBy, insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setGrossRevenueGroupBy, setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

    const GROUP_BY_OPTIONS: LemonSegmentedButtonOption<RevenueAnalyticsInsightsQueryGroupBy>[] = [
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
        {
            label: 'Country',
            value: 'country',
            disabledReason: featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_COUNTRY_GROUPING] ? undefined : 'Coming soon',
        },
    ]

    const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<DisplayMode>[] = [
        { value: 'line', icon: <IconLineGraph /> },
        { value: 'area', icon: <IconAreaChart /> },
        { value: 'bar', icon: <IconGraph /> },
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
                <div className="flex items-center gap-1 text-muted-alt">
                    Group by&nbsp;
                    <LemonSegmentedButton<RevenueAnalyticsInsightsQueryGroupBy>
                        options={GROUP_BY_OPTIONS}
                        value={grossRevenueGroupBy}
                        onChange={setGrossRevenueGroupBy}
                    />
                    <LemonDivider vertical />
                    <LemonSegmentedButton
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                        size="small"
                    />
                </div>
            </div>

            <Query query={query} readOnly context={context} />
        </div>
    )
}
