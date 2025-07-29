import { IconInfo, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useMemo } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import {
    buildDashboardItemId,
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    revenueAnalyticsLogic,
    RevenueAnalyticsQuery,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.GROWTH_RATE
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const RevenueGrowthRateTile = (): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)

    const { queries, growthRateDisplayMode, disabledGrowthModeSelection } = useValues(revenueAnalyticsLogic)
    const { setGrowthRateDisplayMode } = useActions(revenueAnalyticsLogic)

    const query = queries[QUERY_ID]

    const columns: QueryContext['columns'] = useMemo(() => {
        return {
            month: { title: 'Month' },
            revenue: {
                title: 'Revenue',
                render: ({ value }) => <RevenueCell value={value as number} currency={baseCurrency} />,
            },
            previous_month_revenue: {
                title: 'Prev revenue',
                render: ({ value }) => <RevenueCell value={value as number} currency={baseCurrency} />,
            },
            month_over_month_growth_rate: {
                title: 'Growth Rate',
                render: ({ value, recordIndex, rowCount }) => (
                    <RevenueGrowthRateCell
                        value={value as number}
                        hasIncompleteMonthNotice={recordIndex === rowCount - 1}
                    />
                ),
            },
            three_month_growth_rate: {
                title: '3M Growth Rate',
                render: ({ value }) => <RevenueGrowthRateCell value={value as number} />,
            },
            six_month_growth_rate: {
                title: '6M Growth Rate',
                render: ({ value }) => <RevenueGrowthRateCell value={value as number} />,
            },
        }
    }, [baseCurrency])

    const context = useMemo(() => ({ columns, insightProps: { ...INSIGHT_PROPS, query } }), [query, columns])

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-row justify-between">
                <h3 className="text-lg font-semibold">
                    Revenue growth rate&nbsp;
                    <Tooltip title="Growth rate is the percentage change in revenue compared to the previous month. You can also see the more stable average growth rate for the last 3 and 6 months.">
                        <IconInfo />
                    </Tooltip>
                </h3>

                <LemonSegmentedButton
                    value={growthRateDisplayMode}
                    onChange={setGrowthRateDisplayMode}
                    options={[
                        {
                            value: 'line',
                            icon: <IconLineGraph />,
                            disabledReason: disabledGrowthModeSelection
                                ? 'Select data that spans multiple months to see growth rate as a line graph'
                                : undefined,
                        },
                        { value: 'table', icon: <IconTableChart /> },
                    ]}
                    size="small"
                />
            </div>

            <Query query={query} readOnly context={context} />
        </div>
    )
}

const RevenueCell = ({ value, currency }: { value: number | null; currency: CurrencyCode }): JSX.Element | null => {
    if (value === null) {
        return null
    }

    const { symbol, isPrefix } = getCurrencySymbol(currency)
    return (
        <span>
            {isPrefix ? symbol : null}
            {humanFriendlyNumber(value, 2, 2)}
            {isPrefix ? null : ' ' + symbol}
        </span>
    )
}

const RevenueGrowthRateCell = ({
    value,
    hasIncompleteMonthNotice,
}: {
    value: number | null
    hasIncompleteMonthNotice?: boolean
}): JSX.Element | null => {
    if (value === null) {
        return null
    }

    const asNumber = Number(value)
    const percentage = (asNumber * 100).toFixed(2)
    const isPositive = asNumber > 0
    return (
        <span className={cn('text-sm', isPositive ? 'text-green-500' : 'text-red-500')}>
            {percentage}%
            {hasIncompleteMonthNotice && (
                <Tooltip title="Given that the month hasn't finished yet, growth rate is not final">
                    <IconInfo className="ml-1" />
                </Tooltip>
            )}
        </span>
    )
}
