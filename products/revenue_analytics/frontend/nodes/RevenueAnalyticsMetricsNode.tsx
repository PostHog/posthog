import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
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
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import {
    DISPLAY_MODE_OPTIONS,
    extractLabelAndDatasets,
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
} from './shared'
import { getCurrencySymbol } from 'lib/utils/geography/currency'

let uniqueNode = 0
export function RevenueAnalyticsMetricsNode(props: {
    query: RevenueAnalyticsMetricsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsMetrics.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <ARPUTile
                    response={response as RevenueAnalyticsMetricsQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
                <LTVTile
                    response={response as RevenueAnalyticsMetricsQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
                <SubscriptionCountTile
                    response={response as RevenueAnalyticsMetricsQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
                <CustomerCountTile
                    response={response as RevenueAnalyticsMetricsQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
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
): React.FC<TileProps<RevenueAnalyticsMetricsQueryResponse>> => {
    const Component = ({
        response,
        responseLoading,
        queryId,
        context,
    }: TileProps<RevenueAnalyticsMetricsQueryResponse>): JSX.Element => {
        const { baseCurrency, insightsDisplayMode } = useValues(revenueAnalyticsLogic)
        const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

        const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

        const results = ((response?.results as GraphDataset[]) ?? []).filter((result) =>
            result.label?.includes(labelMatcher)
        )

        const { labels, datasets } = extractLabelAndDatasets(results)

        return (
            <TileWrapper
                title={title}
                tooltip={tooltip}
                extra={
                    <div className="flex items-center gap-1 text-muted-alt">
                        <LemonSegmentedButton
                            value={insightsDisplayMode}
                            onChange={setInsightsDisplayMode}
                            options={DISPLAY_MODE_OPTIONS}
                            size="small"
                        />
                    </div>
                }
            >
                {responseLoading ? (
                    <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
                ) : (
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
                )}
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
