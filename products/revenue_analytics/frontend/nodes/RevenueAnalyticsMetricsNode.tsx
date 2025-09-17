import { BindLogic, BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMetricsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { RevenueAnalyticsLineGraph, TileProps, TileWrapper, extractLabelAndDatasets } from './shared'

let uniqueNode = 0

export function RevenueAnalyticsMetricsNode(props: {
    query: RevenueAnalyticsMetricsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsMetrics.${uniqueNode++}`)

    const dataNodeLogicProps = {
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    }

    useAttachedLogic(insightLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(insightVizDataLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), props.attachTo)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <SubscriptionCountTile context={props.context} />
                    <CustomerCountTile context={props.context} />
                    <ARPUTile context={props.context} />
                    <LTVTile context={props.context} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

/**
 * Creates a tile component for displaying revenue analytics data
 *
 * @param title - The title displayed at the top of the tile
 * @param tooltip - Tooltip content explaining the tile's data
 * @param labelMatcher - String to filter the response results by matching against dataset labels
 * @returns A component that renders a graph tile with the filtered data
 *
 * The returned component:
 * - Filters response data to only include datasets with labels matching labelMatcher
 * - Displays a title and tooltip
 * - Shows display mode controls (line/area/bar)
 * - Renders a loading state while data is loading
 * - Renders a line graph with the filtered data once loaded
 */
const makeTile = (
    title: string,
    tooltip: JSX.Element | string,
    labelMatcher: string,
    { isCurrency = false }: { isCurrency?: boolean } = {}
): React.FC<TileProps> => {
    const Component = ({ context }: TileProps): JSX.Element => {
        const { baseCurrency } = useValues(revenueAnalyticsLogic)
        const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

        return (
            <TileWrapper context={context} title={title} tooltip={tooltip}>
                {(response) => {
                    const castResponse = response as RevenueAnalyticsMetricsQueryResponse | null

                    const results = ((castResponse?.results as GraphDataset[]) ?? []).filter((result) =>
                        result.label?.includes(labelMatcher)
                    )

                    const { labels, datasets } = extractLabelAndDatasets(results)

                    return (
                        <RevenueAnalyticsLineGraph
                            data-attr={`revenue-analytics-${title.toLowerCase().replace(' ', '-')}-tile-graph`}
                            datasets={datasets}
                            labels={labels}
                            trendsFilter={
                                isCurrency
                                    ? {
                                          aggregationAxisFormat: 'numeric',
                                          aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                                          aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                                      }
                                    : undefined
                            }
                        />
                    )
                }}
            </TileWrapper>
        )
    }

    Component.displayName = title

    return Component
}

const SUBSCRIPTION_COUNT_TITLE = 'Subscriptions'
const SUBSCRIPTION_COUNT_LABEL_MATCHER = 'Subscription Count'
const SUBSCRIPTION_COUNT_TOOLTIP = (
    <span>
        The number of subscriptions that you had in each period. It also includes the number of new and churned
        subscriptions in that period.
    </span>
)

const SubscriptionCountTile = makeTile(
    SUBSCRIPTION_COUNT_TITLE,
    SUBSCRIPTION_COUNT_TOOLTIP,
    SUBSCRIPTION_COUNT_LABEL_MATCHER
)

const CUSTOMER_COUNT_TITLE = 'Customers'
const CUSTOMER_COUNT_LABEL_MATCHER = 'Customer Count'
const CUSTOMER_COUNT_TOOLTIP = (
    <span>
        The number of customers that you had in each period. This might differ from the number of subscriptions because
        a customer can have multiple subscriptions.
    </span>
)
const CustomerCountTile = makeTile(CUSTOMER_COUNT_TITLE, CUSTOMER_COUNT_TOOLTIP, CUSTOMER_COUNT_LABEL_MATCHER)

const ARPU_TITLE = 'ARPU'
const ARPU_LABEL_MATCHER = 'ARPU'
const ARPU_TOOLTIP = <span>The average revenue per user in each period.</span>
const ARPUTile = makeTile(ARPU_TITLE, ARPU_TOOLTIP, ARPU_LABEL_MATCHER, {
    isCurrency: true,
})

const LTV_TITLE = 'LTV'
const LTV_LABEL_MATCHER = 'LTV'
const LTV_TOOLTIP = (
    <span>
        The lifetime value of a customer. This is calculated as the average revenue per user divided by the churn rate.
        In the rare case where there are no churned customers, the LTV is set to NaN - not displayed.
    </span>
)
const LTVTile = makeTile(LTV_TITLE, LTV_TOOLTIP, LTV_LABEL_MATCHER, {
    isCurrency: true,
})
