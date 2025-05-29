import { IconInfo } from '@posthog/icons'
import { useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useMemo } from 'react'

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
import { revenueEventsSettingsLogic } from '../settings/revenueEventsSettingsLogic'

const QUERY_ID = RevenueAnalyticsQuery.REVENUE_GROWTH_RATE
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const RevenueGrowthRateTile = (): JSX.Element => {
    const { baseCurrency } = useValues(revenueEventsSettingsLogic)

    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    const columns: QueryContext['columns'] = useMemo(() => {
        return {
            month: { title: 'Month' },
            mrr: {
                title: 'MRR',
                render: ({ value }) => <MRRCell value={value as number} currency={baseCurrency} />,
            },
            previous_mrr: {
                title: 'Previous MRR',
                render: ({ value }) => <MRRCell value={value as number} currency={baseCurrency} />,
            },
            mrr_growth_rate: {
                title: 'MRR Growth Rate',
                render: ({ value, recordIndex, rowCount }) => (
                    <MRRGrowthRateCell value={value as number} isLast={recordIndex === rowCount - 1} />
                ),
            },
        }
    }, [baseCurrency])

    const context = useMemo(() => ({ columns, insightProps: { ...INSIGHT_PROPS, query } }), [query, columns])

    return <Query query={query} readOnly context={context} />
}

const MRRCell = ({ value, currency }: { value: number; currency: CurrencyCode }): JSX.Element => {
    const { symbol, isPrefix } = getCurrencySymbol(currency)
    return (
        <span>
            {isPrefix ? symbol : null}
            {humanFriendlyNumber(value, 2, 2)}
            {isPrefix ? null : ' ' + symbol}
        </span>
    )
}

const MRRGrowthRateCell = ({ value, isLast }: { value: number; isLast: boolean }): JSX.Element => {
    const asNumber = Number(value)
    const percentage = (asNumber * 100).toFixed(2)
    const isPositive = asNumber > 0
    return (
        <span className={cn('text-sm', isPositive ? 'text-green-500' : 'text-red-500')}>
            {percentage}%
            {isLast && (
                <Tooltip title="Given that the month hasn't finished yet, growth rate is not final">
                    <IconInfo className="ml-1" />
                </Tooltip>
            )}
        </span>
    )
}
