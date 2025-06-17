import { IconGraph, IconInfo, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButton, LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema/schema-general'
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
    const { queries, insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const query = queries[QUERY_ID]
    const context = useMemo(() => ({ insightProps: { ...INSIGHT_PROPS, query } }), [query])

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
