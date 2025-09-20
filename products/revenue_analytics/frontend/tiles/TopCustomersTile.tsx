import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconInfo, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import {
    REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
    RevenueAnalyticsQuery,
    buildDashboardItemId,
    revenueAnalyticsLogic,
} from '../revenueAnalyticsLogic'

const QUERY_ID = RevenueAnalyticsQuery.TOP_CUSTOMERS
const INSIGHT_PROPS: InsightLogicProps<InsightVizNode> = {
    dashboardItemId: buildDashboardItemId(QUERY_ID),
    loadPriority: QUERY_ID,
    dataNodeCollectionId: REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export const TopCustomersTile = (): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)

    const { queries, topCustomersDisplayMode, disabledGrowthModeSelection } = useValues(revenueAnalyticsLogic)
    const { setTopCustomersDisplayMode } = useActions(revenueAnalyticsLogic)
    const query = queries[QUERY_ID]

    // TODO: Link back to the `person` page when clicking in the name/id
    // This will be solved by having users create a join between this view and the `person` view
    // manually in the data warehouse view
    //
    // This is still a little bit aways because we need to turn our views into actual materialized views
    // rather than just weird virtual SQL views
    const columns: QueryContext['columns'] = useMemo(() => {
        return {
            name: { title: 'Name' },
            customer_id: {
                title: (
                    <span>
                        Customer ID{' '}
                        <Tooltip title="As seen in your Data Warehouse">
                            <IconInfo />
                        </Tooltip>
                    </span>
                ),
            },
            month: { title: ' ', width: '0px', render: () => null }, // Hide month column by setting width to 0 and whitespace string
            amount: {
                title: 'Amount',
                render: ({ value }) => <AmountCell value={value as number} currency={baseCurrency} />,
            },
        }
    }, [baseCurrency])

    const context = useMemo(() => ({ columns, insightProps: { ...INSIGHT_PROPS, query } }), [columns, query])

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-row justify-between">
                <h3 className="text-lg font-semibold">
                    Top customers&nbsp;
                    <Tooltip title="Top customers by revenue in the selected period.">
                        <IconInfo />
                    </Tooltip>
                </h3>

                <LemonSegmentedButton
                    value={topCustomersDisplayMode}
                    onChange={setTopCustomersDisplayMode}
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

            <Query attachTo={revenueAnalyticsLogic} query={query} readOnly context={context} />
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
