import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
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

const QUERY_ID = RevenueAnalyticsQuery.TOP_CUSTOMERS
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const RevenueChurnTile = (): JSX.Element => {
    const { baseCurrency } = useValues(revenueEventsSettingsLogic)

    const { queries } = useValues(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    // TODO: Link back to the `person` page when clicking in the name/id
    // Still need to figure out how to easily do this given that we only have Stripe's customer ID
    const columns: QueryContext['columns'] = useMemo(() => {
        return {
            name: { title: 'Name' },
            customer_id: { title: 'Customer ID' },
            month: { title: 'Month' },
            amount: {
                title: 'Amount',
                render: ({ value }) => <AmountCell value={value as number} currency={baseCurrency} />,
            },
        }
    }, [baseCurrency])

    const context = useMemo(() => ({ columns, insightProps: { ...INSIGHT_PROPS, query } }), [columns, query])

    return (
        <div className="flex flex-col gap-1">
            <h3 className="text-lg font-semibold">
                Top customers&nbsp;
                <Tooltip title="Top customers by all revenue accumulated in the selected period.">
                    <IconInfo />
                </Tooltip>
            </h3>

            <Query query={query} readOnly context={context} />
        </div>
    )
}

const AmountCell = ({ value, currency }: { value: number; currency: CurrencyCode }): JSX.Element => {
    const { symbol, isPrefix } = getCurrencySymbol(currency)
    return (
        <span>
            {isPrefix ? symbol : null}
            {humanFriendlyNumber(value, 2, 2)}
            {isPrefix ? null : ' ' + symbol}
        </span>
    )
}
